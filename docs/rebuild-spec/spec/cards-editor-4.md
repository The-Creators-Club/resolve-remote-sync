# Timeline Cards: the editor, part 4 of 5

This part covers what the assistant does inside the editor (proposals, the join check, shortening a cut to a length, the edit chat, the montage builder and section summaries), and how the editor works with no connection, over a poor one, and on several devices at once, including the Timeline Cards apps for Windows and Android.

## Shortening, the edit chat and the assistant

### What remains of these features when the assistant is switched off

With the site's assistant switch off, none of the controls in this sub-topic that call the assistant is on any screen: there is no Shorten button, panel, Alt+H, Alt+B or Shift+B, no suggestion markers or score shading on the lane; no "Ask Assistant" button in the toolbar or the phone's header, and no chat panel; no "Montage" button, Alt+M or montage drawer; no sparkle button, "Summarise" button or "A new summary is ready" row. What stays:

- Every edit these features would propose can still be made by hand in the editor.
- Cards a past shortening put on the shelf stay on the shelf under their shortening's category, and summaries already written into a cut list stay in the file.
- Proposals from other sources (bringing changes back from Resolve) still arrive and are previewed and accepted as below.
- The join check shows its quick check only, marked "quick check", and no join is ever marked "The join reads well".
- No refusal that says the assistant is unavailable is ever shown, since nothing that would raise it is on screen.

- When the assistant is off: as above.

### Every suggestion from the assistant and every import arrives as a proposal the editor previews and accepts in whole or in part

{{29-065}}

- Who: anyone who can open the editor and write to the cut list.
- When the assistant is off: only proposals that do not come from the assistant (bringing changes back from Resolve) arrive.
- When the help for the editing program is off: nothing is brought back from an editing program, so no proposal comes from one.
- Exact: yes

### Each join between two cuts can be checked for meaning and grammar

When join checks are available (dock lane, tall enough track): a dot on each seam between two cuts in the same section (when the seam and the next cut have room), coloured by its verdict. Hover (mouse) or tap opens a pop-up: "Checking the join…", "The join reads well", "Meaning changed" or "Grammar break", "quick check" when only the quick check has answered, the note, the joined original words, and their fresh English, or "Assistant is reading the joined words again…".

- Phone and desk: hover opens the pop-up with a mouse, a tap opens it on touch.
- When the assistant is off: only the quick check answers, every pop-up carries "quick check", and no join is marked "The join reads well".
- Exact: yes

### Shortening only suggests, and everything it takes out goes to the shelf

Nothing is cut until the editor accepts a suggestion; nothing is ever deleted, removed material always goes to the shelf under the review's shelf category, "shortened <target> <YYYY-MM-DD>". Each accept is its own change with its own undo. If the page that asked closes or reloads before the assistant answers, the work is stopped: "stopped: the page that asked went away before Assistant answered, so nothing was changed"; a stopped section keeps what it had. Server unreachable: "the server could not be reached (<why>); nothing changed".

A shortening is a set of removals only: it never reorders, never inserts and never changes a word. Every removal, once accepted, moves onto the shelf under the shortening's own category, named "shortened <target> <date>" (for example "shortened 12:00 2026-09-11"), so it stays in the file, playable and restorable. Refusals common to every step: "open a cut list first - the chat edits a .cut.md, not a live timeline"; "this cut list is open read only, so nothing can be changed in it"; "shortening needs Assistant: <why>". Every step answers with a sentence rather than failing.

Closing the tab stops the assistant work it started within seconds, and a shortening a person is waiting on never waits behind background work.

- Who: anyone who can open the editor and write to the cut list.
- When the assistant is off: there is no shortening; what earlier shortenings put on the shelf stays there.
- Exact: yes

### An editor opens the Shorten panel from the toolbar, a key or a marker

{{31-022}}

- Ways in: the toolbar's Shorten button, Alt+H, "Open in the panel" on a suggestion marker.
- Name and search words: the Shorten panel: shorten, trim to length, target length, cut down, tighten.
- Phone and desk: a column at the right on a desk, the full screen on a phone.
- When the assistant is off: no Shorten button, and Alt+H does nothing.
- Exact: yes

### The editor sets a target length, steers the assistant in words and limits shortening to some sections

- "Target length" box (hint "12:00, 12m or 60%") and "Plan the cut" button ("Planning…" while busy). Accepted: seconds, `12:00`, `1:02:30`, `720`, `12m`, `12 min`, `90s`, or `60%` (the share to keep, above 0 and under 100). Unreadable in the panel: "a target is a length like 12:00, minutes (12m) or a percentage to keep (60%)"; from the server: "say how long it should be: a length like 12:00, or a percentage of what it runs now". Not shorter than now: "this cut already runs <now>, which is inside <target> - there is nothing to shorten".
- "Or drag to a length" slider, 30% to 100% of the cut's current length in whole percent; the line under it reads "<m:ss> · <pct>% of <now>". Dragging writes the length into the box. Untouched, it sits at the typed target, or 70%. A repaint never interrupts a drag.
- "Steer (optional)" box (placeholder "keep everything with the daughter"), up to 2000 characters, passed to the assistant as the editor's own words.
- Section scope: "Shorten: All <n> sections" / "<k> of <n> sections" opens a tick list of the titled sections with their lengths; "None ticked is the whole cut." With some ticked, the current length is their sum; otherwise the whole timeline including gaps.
- Hint: "Say how long the cut should run. Assistant plans a budget per section first; nothing is cut until you say the plan looks right, and nothing leaves the cut until you accept it."

{{40-076}}

{{40-077}}

Every step of a shortening touches only the sections ticked (none ticked is the whole cut), and a one-section shortening asks of the assistant only what that section needs, so it costs in proportion to that section.

- Exact: yes

### Every card can be scored once, and a slider then previews on the lane which cards would go at any length

- Without scores: "Build the scores once and this slider shows what would go at any length, on the lane, as you drag. One long Assistant call reads every card; it cuts nothing." and "Build the scores" ("Scoring…" while busy; the line says "Scoring every card once. This is the long call, and it cuts nothing."). Done: "<n> cards scored: drag the slider and the lane shows what would go at that length".
- The assistant gives each card a keep score from 0 (nobody would miss it) to 1 (keep firmly), a kind, the cards it depends on (at most 20) and a reason. A card whose words changed later counts as unscored. New scores replace the old ones whole.
- Refusals: more than 3000 cards, "this cut list has more than 3000 cards, more than one scoring call can read; shorten it a section at a time"; "there are no cards to score"; already scoring, "the scores for this cut list are already being built - wait for them"; none scored, "Assistant scored none of the cards, so nothing was saved and the slider still needs them".
- With scores: a line ("Drag the slider: the lane shows what would go at each length, from the scores", or "<n> card(s) would go · lands <m:ss> · from the scores, not a pass", or "nothing the scores would cut · ..."), "<n> of <m> cards changed since they were scored / have no score; they stay at every length. Score again to count them.", "Ask for the real cut at <m:ss>" (plans at the slider's length), "Clear the preview" (when it removes anything), "Score again", and "A guess from the scores, drawn in gold on the lane. The real pass reads the words and suggests; nothing is cut until you accept."
- The preview drops whole cards, lowest keep score first (ties: longer card first), until the target is reached. It never drops a card with a note, the last card of a section, a card a kept card depends on, or an unscored card. It is recomputed when the cut changes, drawn as a gold hatched strip on the lane with no tabs, and cannot be accepted.

{{40-087}}

- Exact: yes

### Planning first gives each titled section a budget that the editor can change before any words are cut

- Only sections with a title count. None: "this cut list has no section headings, so there is no structure to budget. Add headings first, or ask the chat to cut it down in words."
- One plan at a time per cut list: "a shortening is already being planned for this cut list - wait for it". No answer from the assistant: "Assistant gave no answer, so nothing was planned".
- The assistant is told the target, the current length, the difference, which sections are in play, pinned sections, the style for what counts as fluff, each section and each card (cards with a note are marked protected). Its plan is checked against the real sections, with the editor's pins winning, and summed.
- A new plan replaces (closes) any open review of the cut list; what earlier reviews put on the shelf stays there.
- Budget step box: "Looks right: cut the words" and "Pin a section Keep or Drop and the plan is worked out around it. Nothing has moved yet." The target form folds to one line ("target <m:ss>", the steer in quotes, "Change the plan"); unfolded it shows "Plan again" and "Keep this plan".
- Unknown review: "that shortening is not on this cut list any more".

The assistant is given the target, the current length, how much must go, the studio's rubric of what to keep and what to cut first, and each section's card count and length, and answers per section keep, thin (to about N seconds) or drop, each with a reason, plus a two-or-three-sentence note to the editor. A section it left out is kept whole ("Assistant said nothing about this section, so it is kept whole"); a thin with no length, or a length not below the section's own, becomes keep ("the thinning target did not make sense"). Where the plan lands is always the product's own sum (dropped sections count 0, thinned ones their target, kept ones their length), never the assistant's arithmetic. An answer that is not a plan: "Assistant answered with <type> instead of a budget, so nothing was planned". The plan is recorded in the edit chat as a turn "shorten to <t>". The editor can edit the plan table; edited rows are taken as written and re-summed, and pins sent with the table win. Planning gives up after 10 minutes.

A keep, drop or free pin stays through every recalculation and every reload until the editor changes it.

- Exact: yes

### An episode can carry its own description of what counts as fluff

Shortening judges what is fluff by the studio's rubric of what to keep and what to cut first (see Timeline Cards: the board, The owner's editorial rules). When the episode has its own shortening style note and it is not empty, the assistant judges fluff by that note instead; an empty or unreadable note falls back to the studio's rubric. The same note is used for planning, for cutting the words and for scoring.

### The Sections tab shows each section's before and after as a bar, with pins and a length box per section

{{31-027}}

- Exact: yes

### Cut the words has the assistant choose, section by section, which words go, and checks its choices before offering them

{{31-028}}

{{40-079}}

Every section's answer is kept with the cut list, so a section that was cut, failed or was stopped can be cut again after a reload, and when several sections are cut at once every one's result is kept. The progress counts only work really running, and a section that cannot be answered fails visibly within about eleven minutes.

- Exact: yes

### Rules every shortening removal must pass, whatever the assistant says

{{40-080}}

Every card cut inside is shown to the assistant as its kept words with a mark at each seam, and it answers per card "ok" or "fix" with new ranges. A fix passes the same rules; a fix that fails keeps the card whole ("kept whole: the splice did not read"). If the read-back cannot be done, the cuts stand and are marked "unchecked".

- Exact: yes

### Each suggestion says what kind of cut it is, what goes, why, and how long it saves

{{31-029}}

{{40-085}}

- Exact: yes

### The next-step box tells the editor what is left to decide and offers the next actions

{{31-030}}

- Exact: yes

### The Suggestions tab draws the cut as it would run, with each removal hanging under the join it leaves

{{31-031}}

- Setting: Mark them on the lane and the cards. Does: shows or hides the shortening's marks on the lane, the card list, the section rail and the edit view. Default: on. Who: anyone, for their own browser. Applies to: a computer. Search words: suggestions on lane, marks, shorten markers, hide suggestions.
- Exact: yes

### The Read tab shows the budgeted sections as prose with the words that would go struck through

{{31-032}}

- Exact: yes

### Accepting a suggestion takes exactly that stretch out of the cut as it is now, splitting a card where needed, and shelves it

{{31-033}}

{{40-083}}

{{40-084}}

Taking several at once checks that each one really changed the cut and stops with a message naming the one that did not, never repeating it.

- Exact: yes

### The editor can dismiss, bring back and put back suggestions, and nothing is lost from the record

{{31-034}}

- Exact: yes

### The editor can hear a suggestion, or hear the cut as it stands, shortened, or original

{{31-035}}

- Exact: yes

### Shortening has its own keys

{{31-036}}

- Setting: On the lane. Does: draws the shortening's suggestions on the lane in full, as a ribbon only, or not at all. Default: In full. Who: anyone, for their own browser. Applies to: a computer. Search words: suggestions lane drawing, ribbon, hide removals, shorten view.
- Exact: yes

### The review stays current, and is the same in every window and on the phone

{{31-037}}

The whole review is kept with the cut list's chat history, so a reload, a second window or a phone sees the same suggestions in the same states, and decisions made in two places at once are taken one after the other.

- Exact: yes

### Suggestions are marked on the lane, the card list, the section rail and the edit view, and each marker opens a popover

{{31-038}}

- Phone and desk: on a phone the popover is a bottom sheet; on a desk it sits under or above the marker.
- Exact: yes

### Kept cards the scores nearly cut are shaded on the lane

{{31-039}}

- Exact: yes

### An editor opens the edit chat from the toolbar or, on a phone, from the header

Toolbar button "Ask Assistant" (speech-bubble icon, tooltip "Say what to change; Assistant suggests, and nothing changes until you apply one", shown pressed while open). On a phone (up to 700 px wide): an icon button in the editor's header row and another in the edit view's top bar, never floating over content. One panel per page. On desktop it sits over the inspector column (or, if that is hidden, in a 420 px column at the right between the header and the dock); on a phone a full-screen sheet with the composer above the keyboard, closed by the back gesture. Close: X button (hint Esc), Esc (when the text box is not focused; Esc in the box only leaves it), or the toolbar button. Focus returns to the opener. Touch targets 44 px; 16 px text in the box so an iPhone does not zoom on focus.

- Ways in: the toolbar button on a desk, the header button and the edit view's top-bar button on a phone.
- Name and search words: the edit chat: ask assistant, chat, change the cut in words, edit by talking.
- Phone and desk: a panel over the inspector on a desk, a full-screen sheet on a phone.
- When the assistant is off: no button anywhere, and no chat panel.
- Exact: yes

### The chat offers three strengths of assistant, each its own conversation

Header "Ask Assistant" and a picker of three strengths: fastest, stronger, most capable, each with its price as a tooltip; remembered on the device, default most capable. Changing it reloads the state for that strength's conversation.

The chat's strength is a property of the panel: once picked it stays until changed. Each strength is its own conversation, so switching strength reads the material again at that strength's price. An admin can set the chat's default strength for the whole server; a strength the editor has picked on their device always wins over it. Each strength moves to the newest version of the assistant on its own (see The whole product: The assistant), and every call records which version answered.

- Setting: Default strength of the edit chat. Does: chooses which of fastest, stronger or most capable answers the chat for anyone who has not picked one on their device. Default: most capable. Who: an admin. Applies to: the site. Search words: assistant strength, chat model, default model, most capable.
- Exact: yes

### The chat's status line says whether it can work, whether the assistant still has the cut list in mind, and what it is doing

A dot shows running, warm or cold.

- Problems (the box and Send are disabled while any holds): "the chat is not available: <why>"; "open a cut list first - the chat edits a .cut.md, not a live timeline"; "the chat needs Assistant on this server: <why or 'not installed'>".
- While a turn runs: "<status>, <n> s", counting each second (no progress bar). Statuses: "reading the transcripts, part k of n", "thinking", "checking the suggestions against the cut list".
- Otherwise "Warm, <n> turns in" or "Cold: the next message reads everything", then "<n> transcripts" (", changed since" when the conversation holds older ones), "no transcripts", or "transcripts could not be read", and any note. Tooltip: "<strength>: it still has this cut list in mind" or "...the first message reads the transcripts and the whole cut list", and "<n> transcripts in <k> parts".
- The state is reloaded after every turn.

{{40-074}}

Whether the assistant is available is shown from the last real check, and showing it never spends a paid call. A check that has not answered yet, or an assistant that is only slow to start, is never reported as missing: a slow start reads "too slow to start" and is checked again within about 30 seconds.

- Exact: yes

### The editor types what to change in plain words and sends it, and the assistant answers with up to four proposals

- Composer placeholder "Say what to change, in your own words", or "Apply one of these, or say how to change them" when the newest turn has proposals waiting. Enter sends; Shift+Enter is a new line (not while an input method is composing). Buttons "New conversation", "Send", and "Stop" while a turn runs (stops it on the server and in the page).
- One message at a time; the message appears at once and the reply streams in with a blinking caret.
- Refusals: "the request is not a chat message"; empty, "type what you want changed"; over 4000 characters, "that message is over 4000 characters: say it in fewer words"; no cut list, "open a cut list first - the chat edits a .cut.md, not a live timeline"; assistant unavailable, "the edit chat needs Assistant: <why>"; a turn already running for this cut list, "Assistant is still working on the last message".
- Errors: "Stopped. Nothing was asked of the cut list."; "the chat stopped answering before it finished"; "the chat did not answer: <why>". Closing the page stops the turn.
- The answer is one to three sentences and up to 4 proposals (title, why, steps). Not usable: "Assistant answered with something that is not an instruction, so nothing was changed". Empty: "Assistant answered with nothing to say and nothing to suggest. Try asking again in other words."
- Empty history text: "Say what to change, in your own words: "drop the second pangolin story and move the handbook cut to the end". Assistant answers with suggestions; nothing changes until you apply one, and each one is a single undo step."

Further refusals: "the cut list changed under you - the page has reloaded, ask again"; "Assistant answered with <type> instead of an instruction, so nothing was changed"; "the Assistant session was lost twice running: give it a moment and retry"; "the Assistant session could not be opened: the provider refused the id twice running".

While the editor is offline the chat refuses to send and never keeps a message to send later.

- Exact: yes

### The chat knows the whole episode's transcripts, the whole cut list and what the editor is pointing at

- It is given every interview and clip transcript of the episode, the cut list (frame rate, every card with speaker, time, colour, words, highlights and note; gaps; sections, headings and notes with times, card counts and lengths), the staged shelf by category, saved sequences and alternates.
- With each message the page sends the playhead time, the selected cards in click order and the current view; the card under the playhead is worked out from the time, and the assistant is told which card and how far in (or "not on a card"), the selected cards with their words and section, and what became of the last turn's proposals ("last turn: proposal "<title>" was applied" / "last turn: none of the <n> proposals was applied").
- Warm for an hour after a completed turn; cold otherwise, or when the transcripts or house style changed. A cold message is slow because it reads everything again; a warm one sends only what changed in the cut list.
- Why a new conversation was opened, shown as "opened a new conversation: <why>": "the first message of the session reads the transcripts and the cut list"; "the house style changed since the last message, so it and the cut list were read again"; "the transcripts changed since the last message, so they and the cut list were read again"; "the conversation had gone cold (over an hour), so the cut list was read again"; "the conversation could not be dated, so the cut list was read again"; "the Assistant session was lost (new machine or a rebuilt server), so the cut list went in again". Lost twice: "the Assistant session was lost twice running: give it a moment and retry". Refused twice: "the Assistant session could not be opened: the provider refused the id twice running".
- Transcripts that cannot be read do not stop the turn: "the transcripts could not be read (<why>), so nothing can be brought in from them this turn".
- Two browsers on the same cut list and strength share one conversation.
- "New conversation" (tooltip "Start over: the next message reads the transcripts and the whole cut list again"; disabled while busy, refused while a turn runs with "Assistant is still working on the last message") keeps the history and adds the divider "new conversation: the next message reads the transcripts and the whole cut list again".
- The chat never changes a transcript.

On a cold start the assistant reads every transcript of the episode (all interviews and montage source clips), then its rules, the house style and the whole cut list, then the editor's message. With no transcripts, it is told that the cards are the only material there is. Every message sends the cut list as it is now; a card the conversation has already seen in full is shortened to its first 60 characters (highlights still shown), and a trimmed or split card is sent in full again. A cold message gives up after 15 minutes, a warm one after 10.

The cards selected now, and those staged on the shelf, travel with the message in the order selected, each with its label, person, timecode, text (up to 120 characters) and section, group and lane (up to 80 characters). Beyond 40 cards the rest are still named one by one, so the count and the list always agree.

{{40-068}}

- Exact: yes

### The chat follows a house style of seven editorial rules, which an episode can replace with its own

The built-in house style has seven rules: no interviewer questions ever; withhold, then reveal; part of a sentence can be the whole card; end sections on a cliffhanger; space revelations out; never invent tension (the speakers' own words in their own order); cut it as one conversation across speakers, choosing each card as a reply to the one before it in cut order. An episode's own chat style note, when present and not empty, replaces these whole (where it is written is described under Timeline Cards: the board, The owner's editorial rules). When the editor's request conflicts with the style, the assistant does what was asked and says what the style would have done. When the transcripts or the house style change, the next message works from the new ones and says which of the two changed.

### The chat proposes, and the editor decides

Nothing the assistant writes is applied when it writes it. Each answer is one to three plain sentences and, optionally, proposals, each with a title, a reason and the changes it would make: one proposal when there is one obvious way, up to four only when they are real alternatives. An answer with no proposals is a question or an answer, which is right whenever guessing would be needed. A follow-up revises the same request. The assistant uses the smallest set of changes, never invents a card, quotes card words exactly, brings in new material only from the transcripts by paragraph identity with exact words, knows a paragraph without word timing cannot be cut, and asks when the request is ambiguous. Words like "here", "this card", "the playhead" and "what I have selected" mean what the editor's screen shows.

### A proposal can move, delete, stage, trim, split, gap, colour, note, highlight, section and insert, each with a plain result line or a reason it cannot

A proposal may name cards in the cut or on the shelf, the card under the playhead, the selected cards, or a card made earlier in the same proposal. "At the playhead" means before the card under it if the playhead is in its first half, else after it. Matching a card's words ignores case and spaces ("我今年19歲" matches "我今年 19歲"). Each change is one revision of the cut list.

| Step | Does | Result line | Refusals |
|---|---|---|---|
| move | cards before/after a card, to the start or end (the end when nothing is said), or at the playhead | "moved <n> card(s) <where>" | "those cards are already there"; "a card cannot be moved before or after itself"; "that card is the one the playhead is in, so there is nowhere to move it to"; "no card was named to move"; "the card under the playhead is not in the cut list any more"; "the card to move before/after is not in the cut list any more" |
| delete | takes cards out onto the shelf under their section's name | "deleted <n> card(s) (onto the shelf under its section)" | "no card was named to delete" |
| stage | shelves cards, optional category | "staged <n> card(s) [under <cat>]" | a category that is not text |
| unstage | a shelf card back into the cut at a place | "put a staged card back into the cut <where>" | "Assistant named a staged card that is not on the shelf (<uid>). Nothing was changed." |
| trim | keeps the words from one phrase to another (either may be left out), at most a head and a tail trim, cutting at the middle of the silence between words; the card's words become the kept words, highlighted unless told not to | "trimmed a card to keep "<from> to <to>" [(highlighted)]" | "a trim needs the words to keep: keep_from, keep_to, or both"; "<to> comes before <from> in that card, so there is nothing between them"; "that card already begins and ends on those words, so there is nothing to trim" |
| split | blades a card just before the first word of a phrase; each half gets its own words and the highlights that fit | "split a card before "<phrase>"" | "'<words>' is the start of that card, so there is nothing to split off before it" |
| gap | sets the black before a card, in seconds turned into frames at the cut's rate; 0 removes it | "put <n> s of black before "<card>"" / "removed the gap before "<card>"" | "Assistant asked for a gap of <x>, which is not a number of seconds. Nothing was changed."; "there is no gap before "<card>" to take out" |
| color | sets or clears a Resolve clip colour: Orange, Apricot, Yellow, Lime, Olive, Green, Teal, Navy, Blue, Purple, Violet, Pink, Tan, Beige, Brown, Chocolate, or empty to clear | | "<colour> is not a Resolve clip colour. Nothing was changed." |
| note | writes or clears a card's note (cut or shelf) | | |
| highlight | marks or clears words of a card (cut or shelf); they must be its own | | ""<text>" is not in that card. Its words are: "<first 80 chars>"" |
| section add | a section heading (Blue) or note heading (Green) before a card, at the playhead's exact frame, or at the end (the end when nothing is said) | | "a heading needs a title" |
| section from | gathers the named cards where the first sits under a new section heading | "grouped <n> card(s) under the new section "<title>"" plus "(the cards after it stay under it until the next heading)" | "no card was named to group"; "none of those cards is in the cut list any more"; "the first card of the group is not in the cut list any more" |
| section remove, rename, move | headings found by title, any case; move before a card's section (the section that card begins, or the next one), above another section, at the playhead, or to the end; a heading added earlier in the same proposal can be renamed, moved or removed later in it | | "there is no heading called "<title>" in this cut list. Nothing was changed."; "more than one heading is called "<title>", so it is not clear which one was meant. Nothing was changed."; "Assistant named no heading. Nothing was changed."; "a rename needs the new title"; moving a note ("is a note, not a section"); "a section cannot be moved above itself" |
| insert | new material from a transcript paragraph by its ref, optionally narrowed from one phrase to another (looked for in the original line first, then the English), optionally naming the person when two share a ref; placed like a move, at the playhead (splitting the card under it when both halves would be at least the minimum card length), or onto the shelf under a category; the words are placed in the clip's word timing like a highlighted selection, and the narrowed words are highlighted on the new card | "inserted <n> s of <speaker> ("<from ... to>") <where>" plus "(the whole paragraph: the words could not be narrowed)" or "(the highlight would not fit the words, so it was left off)" | no ref; "this episode has no transcripts to insert from"; "there is no paragraph ^<ref> in this episode's transcripts"; "^<ref> is <A>'s, not <B>'s: name the block you meant"; "^<ref> is in more than one transcript (A and B), so it is not clear which was meant: say whose it is"; "that block is a question, and questions are never in the edit" (always enforced); "'<name>' has no word timings yet, so there is no span to cut - transcribe that clip first"; "that paragraph has no words in it"; "'<words>' is not in paragraph ^<ref>. Its words are: '...'"; "Assistant asked to shelve the new card under <x>, which is not a category name." |

Common refusals: "Assistant named no card."; "Assistant named a card that is not in the cut list (<id>)."; "Assistant named a staged card that is not on the shelf (<id>)."; ""<new:x>" is not a card this proposal has made."; "the page did not say where the playhead is, so there is nothing here to point at"; "the playhead is not on a card right now, so there is nothing under it to name"; "nothing is selected on the page right now"; ""@selected" is more than one card here, and this op takes one"; "a selected card is no longer in the cut list"; "Assistant asked for something this cut list cannot do (<name>)."; "that card has no word timing, so its own words cannot be found in it"; ""<words>" is not in that card. Its words are: ..."; ""<words>" is in that card, but not on any word that can be timed". Most end "Nothing was changed." A proposal that fails keeps showing, marked invalid with the reason naming the step ("step <i> of <n> (<op>): ..."); one that changes nothing: "that would change nothing".

A change that keeps given word ranges of a card and shelves the pieces dropped is used only by shortening, never by the chat. Any part of a paragraph the assistant keeps or inserts is highlighted exactly as the words that will play, and a highlight that cannot fit never costs the card.

- When the help for the editing program is off: the colour step and its refusal say "clip colour" without naming the editing program.
- Exact: yes

### Every proposal is checked and previewed before the editor sees it

Each turn returns up to 4 proposals. Each is checked and previewed in the exact words applying it would report; one that fails a check is still shown, with its reason. Checks: "Assistant asked for something this cut list cannot do (<op>). Nothing was changed."; "Assistant named a card that is not in the cut list (<uid>). Nothing was changed."; "Assistant asked to bring in a paragraph without saying which one. Nothing was changed."; a heading with no title; and each change's own checks above. Nothing is applied. With nothing said and nothing proposed: "Assistant answered with nothing to say and nothing to suggest. Try asking again in other words."

{{31-048}}

- Exact: yes

### Applying a proposal is one click, applies whole or not at all, and can be undone while nothing has changed since

{{40-071}}

One gesture undoes every change the proposal made. It is refused unless the cut list is still exactly as the proposal left it, with the refusal shown on the proposal card above. Also "none of those suggestions has been applied, so there is nothing to undo", "that one has been undone already", "that one changed nothing, so there is nothing to undo".

- Exact: yes

### The chat keeps each cut list's conversation and history, shared by every browser and following a rename

{{31-049}}

{{40-064}}

- Exact: yes

### Chat messages carried over from the studio's earlier Timeline Cards are shown read only

{{31-050}}

- Exact: yes

### The edit chat works only on an open cut list that can be written

{{40-062}}

- Exact: yes

### The montage builder is a drawer where a montage is described in words

- A drawer titled "Montage builder". Ways in: toolbar button "Montage" (shows "Alt M", tooltip "Describe a montage and Assistant cuts it from the corpus", pressed while open); Alt+M toggles it. Close button (shows "Esc") and Escape close it; focus returns.
- Desktop: a 468 px drawer at the right, from under the header down to the top of the lane, at least 600 px tall (it reaches over the lane's right-hand end when the panels are shorter, or up over it when the lane is docked on top). Phone (700 px or narrower): the whole screen.
- Every key typed in the drawer is kept from the editor's shortcuts.
- "Describe the montage" text box (5 rows, at most 8000 characters, spell-checked), with an example placeholder. Ctrl+Enter (or Cmd+Enter) sends; plain Enter is a new line. With a proposal showing, the box shrinks to 64 px.
- Buttons: primary "Cut the montage" (shows "Ctrl Enter"; secondary once a proposal is showing) and "Revise it" (enabled only after a montage exists in this conversation; tooltip "Change the last montage: same conversation, a sentence, seconds" or "Cut a montage first, then ask for changes"). Both disabled when the assistant is unavailable, the status could not be read, or the episode has no corpus (the tooltip says why).
- While working: a busy "Cutting" / "Revising" and a red "Stop".
- Status line (with an icon by tone): "asking the server…"; "starting…"; "reading the corpus, part <k> of <n>…" / "reading the corpus…"; "cutting the montage…" / "revising the montage…"; "finding the words in each clip…"; a lost-session note in front; failure or cancellation reasons; "the montage builder needs Assistant on this server: <reason>"; "this episode has no corpus yet: transcribe some clips into [the episode's montage sources] first"; "the corpus is already in this conversation: ask for a change and it comes back in seconds"; "say what the montage should be, and Assistant reads the corpus once (<n> clips)"; "<n> cuts in <n> sections (answered in <s> s): look it over below, then insert it or discard it".
- Session line: "Conversation <first 8 characters of its id> · <n> turns" and "Start a new conversation" (tooltip "Forget this conversation: the next montage reads the corpus again"; hidden while working). After a reset: "a new conversation: the next montage reads the corpus again". A reset while one is running is refused: "a montage is being cut: stop it first".
- Local messages: "say what the montage should be first" (empty box), "the montage builder could not be reached: <reason>".
- While the drawer is open it checks progress every second while a montage is being cut, every 10 s otherwise, every 5 s after a failed check. A change of cut list resets the drawer.

- Ways in: the toolbar's Montage button, Alt+M.
- Name and search words: the montage builder: montage, describe a montage, cut from clips, sequence from sources.
- Phone and desk: a drawer at the right on a desk, the whole screen on a phone.
- When the assistant is off: no Montage button, Alt+M does nothing, and there is no drawer.
- Exact: yes

### Describing a montage gets a cut list of it from the episode's montage sources, and a follow-up revises it

The editor describes the montage in words. The assistant chooses extracts from the episode's transcribed montage source clips (every one of them is material, whether a cut uses it or not), orders them, groups them into titled sections shaped by what the material wants (a cold open, the threat, the argument) and gives each cut a reason of under 12 words. A follow-up is a revision: the assistant keeps what still works, changes what the note asks for, and gives the whole list again. There is one conversation per cut list, remembered with it, separate from the edit chat's.

The rules the assistant works to, which decide what the editor gets:

- A cut is a span of one clip, named by quoting the clip's own words exactly: never paraphrased, translated or tidied.
- Languages stay mixed through the whole piece, and an English speaker is never put over a Mandarin one to say the same thing: a soundbite is never dubbed.
- The cut is spread across the sources without filling a quota, and long runs on one clip are allowed.
- Every quote must be words actually said, and the assistant says when the material cannot carry a beat.

One describe or one revise gives up after 15 minutes; the whole job, reading the material in included, is stopped after 60 minutes with "the montage took longer than 60 min and was stopped".

A conversation keeps the material it was started with and its most recent turns, 40 turns in all, dropped in whole question-and-answer pairs. Starting a new conversation replaces the old one. When a conversation has been lost, the next turn says so, once, and reads the material again. An answer from the assistant that holds no montage, or one that cannot be read, is reported as such, with the end of the reply shown.

- When the assistant is off: there is no montage builder.

### The assistant reads the episode's corpus once per conversation, so a revision comes back in seconds, and every failure says why

- The corpus is the episode's transcribed montage clips. With none: "this episode has no corpus yet: transcribe some clips into [the episode's montage sources] first".
- The corpus goes into one conversation with the assistant once, part by part; later requests are a sentence in the same conversation, so a revision comes back in seconds. A conversation that did not finish reading the corpus is started again from the first part. The conversation is remembered per cut list (and corpus) on the server, not in the cut list.
- A conversation the assistant no longer knows (a new machine or a rebuilt server) is reopened once: "the Assistant session was lost (new machine or a rebuilt server); re-reading the corpus". Lost twice: "the Assistant session could not be opened: the provider refused the id twice running" or "the Assistant session was lost twice running - give it a moment and retry".
- Revise refusals: "there is no montage to revise yet: cut one first"; "the corpus has changed since the last montage, so there is no montage to revise in this conversation: cut it again".
- The assistant's quotes are found in the clips' words to the frame, falling back to the whole transcript segment; a quote found nowhere is kept as unmatched; a clip not in the corpus is listed as dropped. A corpus re-transcribed meanwhile: "the corpus changed while the montage was being cut - ask again and it reads the new one". No placeable cuts: "the model proposed no cuts this server could place - try saying it another way"; no sections: "the model's answer has no sections - try saying it another way".
- Other failures: "the montage builder needs Assistant: <reason>"; "the corpus could not be read into the conversation: <reason>"; "the model run produced no usable output: <reason>"; "the montage helper answered without the corpus prompts"; "the montage helper answered with something that is not a montage"; "the montage took longer than <n> min and was stopped".
- Limits: one describe or one revise gives up after 15 minutes, and the whole job is stopped after 60 minutes ("the montage took longer than 60 min and was stopped"); at most 200 sections, 2000 cuts per section, quotes of 2000 characters; a request of at most 8000 characters ("a montage note is at most 8000 characters"); one montage at a time per cut list ("a montage is already being cut for this cut list"); at most two at once across the server ("<n> montages are being cut already - try again when one is done"); "that cut list is not in the episode"; "the server is shutting down".
- "Stop" ends it: "stopped: nothing was changed". Stopping the server stops every running montage. Nothing is written to the cut list until the person inserts.

Refusals before starting: "say what the montage should be first"; "the montage builder needs Assistant: <why>"; the cut list's read-only reason or "this cut list is open read only"; "the montage builder writes a cut list, so it needs one open"; "a describe is already running". States shown: opening (with "part k of N"), describing, writing, done (cuts, sections, unmatched, dropped clips, seconds), failed.

- Exact: yes

### The montage builder's answer is placed as cards, and nothing it proposed is silently lost

A clip that is not among the episode's montage sources is dropped. Each quote is placed in its clip's word timing when it matches closely (about 75% alike or better, with handles kept off neighbouring speech); otherwise the passage holding its first words is used; otherwise the cut stays in the file as an "unmatched" note "<stem> -- <quote>". Sections become section headings and each cut carries its reason as its note. With nothing placed and nothing unmatched: "the model proposed no cuts this server could place - try saying it another way". Only the cut is replaced: the cut list's header facts, its shelf, its shelf categories and its saved sequences are kept. The cut list gets a new revision, stamped written "<time> by the montage builder", saved with history and reloaded.

Before anything is inserted, the montage is shown in the drawer: its sections and cuts in order, each with its reason, and a list of every quote that could not be placed and every clip that was dropped. Each cut there plays where it stands, and any cut can be dragged from the drawer into the cut list at the place it is dropped, so a person can take part of a montage by hand as well as insert or discard it whole.

- Exact: yes

### The assistant writes a one- or two-sentence summary of a section into the cut list, undoably


  - The sparkle button asks the assistant for a summary of the section's words (each cut as "<person>: <words>", up to the next heading of any kind; note rows do not end a section). Disabled with "Nothing in this section to summarise", "Section summaries are not available here", or "The summary needs Assistant on the server: <reason>".
  - Refusals before sending: "Nothing transcribed between this marker and the next, so there is nothing to summarise."; "The summary did not start: <reason>".
  - When this page's answer comes back it is written into the cut list as ONE undoable edit under the heading, together with a fingerprint of the words it was written from: "Summary of "<title>" written into the cut list. Ctrl+Z takes it out." Section gone: "The summary came back, but its section is no longer in this cut list." A failed run: "The summary did not come back: <reason>".
  - Under each heading: the stored summary, a gold "Out of date" chip when the words changed since, and a "Remove this summary" button ("Summary removed from the cut list. Ctrl+Z brings it back.").
  - An answer this page did not ask for (another device, a reload) that the cut list does not have: "A new summary is ready", the text, "Keep it" (or "Use this one" when a summary exists; it writes it: "Summary written into the cut list. Ctrl+Z takes it out.") and "Discard".
  - The panel checks for running summaries every 1.5 s, even while shut when this page is waiting for its own answer, for up to about 10 minutes. "Summaries could not be read: <reason>" on the status line when that fails.
  - A change of cut list forgets all summary state.
  - The summary is ONE sentence, two at most, 35 words in all, plain English, no preamble. An empty answer is a failure ("Assistant returned nothing"). One summary per section runs at a time (asking again joins it); at most two run at once across the server ("other summaries are still being written; try again in a moment"). Limits: title 300 characters, section text 60 000 characters. A summary gives up after 5 minutes. Answers wait on the server for 30 minutes for a page to take them; the server writes nothing itself.

- Ways in: the overview's sparkle button, a folded section's "Summarise" button, and the "A new summary is ready" row for an answer this page did not ask for.
- When the assistant is off: no summary is asked for or offered; summaries already written into the cut list stay in the file.
- Exact: yes

### Which strength of assistant each feature of the editor uses, and what it costs

The edit chat's chosen strength (fastest, stronger or most capable) is the one that answers every call the chat and shortening make: planning, cutting the words, reading the joins back and scoring. The montage builder and section summaries use the same choice, so no assistant feature of the editor runs at a strength the person cannot see and change. The transcript search keeps its own choice (see part 3 of this editor). A strength the product does not recognise is quietly given the feature's default, and every call records which version of the assistant answered and what it cost.

Every assistant task started in the editor shows what it is expected to cost before it runs: building the scores, planning a shortening, cutting the words of the sections in play, a chat message (a cold one, which reads everything, costs more than a warm one, and says so), cutting or revising a montage, and a section summary. Each counts against the site's one daily budget for the assistant (see The whole product: The assistant); once the day's budget is spent, the task is refused with that budget's own sentence and nothing in the cut list changes. No feature of the editor has an allowance of its own.

- When the assistant is off: there is no choice of strength, since nothing calls the assistant.

#### Lessons

- Met: CE1-021, CE1-022, CE1-024, CE1-025, CE1-026, CE1-028, CE1-029, CE2-090, CE2-092, CE2-094, CE2-097, CE3-055, CE3-056, CE3-057, CE3-058, CE3-064, CE1-023, CE1-027, CE1-030, CE1-031, CE1-032, CE2-088, CE2-089, CE2-093, CE2-095, CE2-096, CE2-098, CE2-099, CE3-059, CE3-060, CE3-061, CE3-062, CE3-063.
- Met for another part: CE3-054 (in "The montage builder's answer is placed as cards, and nothing it proposed is silently lost").
- Not yet met by any behaviour above: CE2-091 (it is about the transcript search, written in part 3 of this editor), CE2-100 (held staged edits belong to the hand-over to Resolve).

## Working offline, connections and several devices

### Only signed-in people reach the editor

Every page and file of the editor needs a sign-in to the dashboard; anyone not signed in is sent to sign in, and comes back to the page they asked for afterwards. The editor knows who the person is by their sign-in name (up to 120 characters), and that is the name other people see. The live connection that keeps devices in step is refused without a sign-in, or when it comes from another site. Video and audio play and seek normally through the server, so the editor opens and plays on a computer or phone that holds none of the project's files.

- Who: anyone signed in to the dashboard.

### Several people and devices edit one cut list live, and every edit is saved before it counts

Every device with a cut list open sees every edit anyone makes, its own included, as soon as it is saved: another device shows a change within seconds. An edit is confirmed to the device that made it only once it is safely stored, by the answer to that edit itself; an edit that does not apply is refused with its sentence and changes nothing. Sending the same edit twice is harmless: the first answer comes back. A device that joins gets the whole cut list; one coming back gets what it missed, or the whole cut list when its copy no longer matches. Warnings of the last 10 minutes (up to 20) are shown to anyone who joins in that time. Anything a device sends that cannot be read is ignored with the warning "a message I could not read was ignored".

One cut list has one stored copy, which every device reads and writes, so two writers never erase each other's work: a write that finds the cut list changed underneath it is refused and worked out again, never laid over the other. The staged shelf, the notes and every saved plan are part of that one copy, so a phone and a desk never hold two drafts of the same cut list, and every device opens it in the same editor, the same way. Every edit, its time and who made it are kept in the cut list's history (see Editing, undo and the cut list): who is a person's device, a hand edit of the file, or the editor's own automatic work, decided by where the edit came from.

At most 64 devices may have one cut list open at once ("too many editors have this cut list open"), and at most 256 may be connected to the server ("too many editors are connected to this server"). An editor page too old for the server is told plainly to reload the editor. A device dropping its connection is ordinary and is never reported as a fault.

- Who: anyone who can open the editor.

### Opening a cut list shows this device's copy at once, offline or not

Opening a cut list clears the in / out range and the notices, loads that list's undo history, puts this device back where it last was on that list with playback stopped (a device new to the list starts at the latest place any device saved), and shows the connection as "connecting". The editor shows what this device has (the last saved copy plus every unsent edit) at once, before the server answers. With no saved copy, the editor opens it from the server, and from the device's offline copy of the page when offline. Every edit applies on screen at once and is sent only once it is saved on this device; edits reach the server in the order they were made, and everything not yet confirmed is sent again after a reconnect, never applied twice. Closing a cut list (or opening another) saves everything and stops playback.

- Exact: yes

### The editor shows its connection state, and reconnects by itself

{{28-078}}

A connection that has heard nothing for about 45 seconds is dropped and reconnected. A device too slow to keep up is dropped and catches up when it reconnects. Edits made while the connection was down are kept on the device and, on reconnecting, applied in order on top of the newest cut list.

- Exact: yes

### A sync pill in the header always says whether edits are saved

The pill (a dot with a short label; the long label is the hover and spoken name) shows on the desk and on phones, in every view including the edit view on a phone, and is hidden only when no list is open. It is calm while live and loud while the editor works from its own copy with edits waiting.

| State | Long label | Short label | Tone |
|---|---|---|---|
| Offline | "Offline" / "Offline, N queued" | "Offline" / "Offline N" | warning (gold) |
| Connecting, with edits queued | shown as Offline | as Offline | warning (gold) |
| Connecting, nothing queued | "Connecting" | "Connecting" | busy (cyan) |
| Syncing | "Sending N" or "Syncing" | "N queued" or "Syncing" | busy (cyan) |
| Signed out | "Signed out[, N queued]: sign in again" | "Signed out" | warning (gold) |
| Other error | "Not saved" ("Error" with no message) | | error (red) |
| Live | "Saving N" or "Saved" | "N queued" (cyan) or "Saved" | saved (green dot) |

The short count is capped at "99+".

- Phone and desk: the pill shows in every view on both.
- Exact: yes

### While working offline by choice the pill says so

While the Work offline switch is on, the pill reads "Offline (your choice)", followed by " · N edits waiting" when edits are waiting and " · saved <time>" when the device has saved them, so offline by choice is never mistaken for a server that cannot be reached. The header's "Offline" button and the switch's own sentences are described under "A person can choose to work offline even with the server up".

- Phone and desk: the same on both.

### What the editor says when the server refuses an edit, a connection fails for good, or the sign-in has expired

{{28-079}}

- Exact: yes

### When the server cannot save edits, the person is told and nothing is lost

If the server cannot store edits, none of them is confirmed, and every device is told "could not save to the edit history (<reason>); your edits are kept in the editor and will be sent again". The device reconnects and sends them again in order, and its later edits wait until the failed one has arrived, so edits never land out of order. If the cut list's history itself cannot be put right, no edit is saved until the cut list is opened again, and the edits stay waiting on the devices that made them.

### Errors never blank the screen: they say what is kept and offer to sign in, retry or keep working

With no list loaded an error replaces the screen; with a list loaded it is an overlay over the cards until "Keep working" hides it for that message (a different message shows it again).
- Signed out: "Your sign-in has expired.", gold chip "N edit(s) waiting" / "Nothing waiting", "Nothing is lost. Your N edits are kept on this device and sent once you are signed in. Sign in again, and the editor comes back here." Buttons "Sign in again" (to the sign-in page and back to this page) and "Keep working".
- Not found (the message says there is no such cut list): red chip "Not found", "Check the name, or open another cut list. Nothing has been changed."
- Anything else: red chip "N edit(s) not saved" / "Not saved", "Nothing is lost. Your N edits are kept on this device. Try again, or keep working: edits are queued until the server answers." Buttons "Retry now" and "Keep working".
- Messages from elsewhere in the product get a capital first letter, a double hyphen becomes a single hyphen, and "no cut list X" reads "no cut list called X".

- Exact: yes

### Two tabs on one cut list never lose each other's edits

{{28-081}}

- Exact: yes

### Every editor window open on one cut list stays in step with the others

{{32-043}}

- Exact: yes

### A cut list renamed on one device is followed by every other device

When a cut list is renamed, a device still holding the old name is moved to the new one and told: "this cut list was renamed to "<new name>" on another device; your edits go there". Edits held offline under the old name land on the renamed list. Renaming it back undoes the forwarding, and a chain of renames is followed to the end.

### The note editor warns about changes from another device, a vanished gap, and a refused save

{{33-038}}

- Exact: yes

### Each device comes back to where it was, and a device new to a cut list starts at the latest place

Every device on a cut list shares the one cut list, its staged shelf and its notes, while what a person is looking at stays with each device: the selected card, the card at the top, the view (lane or cards), the lane's position, zoom and scroll, the cursor and the playhead. Opening a cut list on a device puts it back where that device left it; a device's first visit to a cut list starts at the most recent place any device saved. Places are remembered for the 24 most recent devices of each cut list.

### Every signed-in person sees who is working in which episode

The list of episodes opens without loading any of them, and two people can each open and edit a different episode, or the same one, at the same time. On the dashboard's list of episodes, every signed-in person sees who is working in which open episode: "<who> is in it now" (within the last minute), "<who> was last in N min ago", or "<who> opened it <how long ago>". A person counts as working in an episode while they really are, offline or on a phone that has gone to sleep included, and an episode stays occupied while any of its devices holds edits not yet sent. Closing an episode asks first, naming who was last in it and when: "Close <episode>? <who> was last in N min ago. Anything an offline browser has not sent yet stays in that browser until it reconnects."

- Who: anyone signed in.
- Ways in: the dashboard's list of episodes.

### The editor opens with no network once it has been opened on that device

After the editor has been opened once on a device with a connection, it opens on that device with no network: from a bookmark, from the installed editor on a phone or computer, or from the home screen, whatever extra words are in the address. With the server not answering at all, the episode list appears within about 3 seconds with its episodes listed; with the connection refused or the device offline, within 2 seconds. After the editor itself has been updated, one visit with a connection is enough for the next offline launch to show the list. Opening an episode saves that episode's page on the device.

Whether the server can be reached is measured with a short check of about 3 seconds, never read from the browser's own online flag (a laptop's browser says it is online while the server cannot be reached). Only short checks that keep failing switch the editor to its own copy: one slow answer never does, and a long request is never cut short for being slow.

A new version of the editor is picked up as soon as the device is online. A sign-in page or a failed answer is never kept as if it were the editor. Updating, moving or retiring any page of the product never deletes a cut list kept on the device or an edit waiting to be sent, and an installed editor claims only its own pages, never another part of the site, whatever address the site is reached at.

- Who: anyone who has signed in on that device before.
- Phone and desk: the same on both.

### What works offline and what needs the server

Offline, the editor still has the last cut list it saw, each clip's facts and its waveform, and every edit can be made. For a cut list kept on the device (see the On this device panel below), every part of the editor works with no network, with nothing different to do:

- the English, the links between English and original words, the language aids and the join checks gathered while online are shown whole;
- search is a plain search of the kept transcripts (any letter case, or exact when the query is in double quotes), up to 200 results, including matches in the cards' text, and the results are marked approximate;
- sound and waveforms of kept clips come from the device, online or not, so scrubbing and trimming need nothing from the server; a stretch of sound the kept copy cannot play is fetched from the server when there is one;
- the kept preview video plays from the device, seeking included; only a completely kept preview is used;
- a seek anywhere in a kept clip of any size resumes playing within a fraction of a second, and skipping between clips starts playback in under a second;
- audio kept at a different rate (Smaller audio, or a sound device changed since it was kept) is converted so it still plays.

While the server can be reached, it is still asked first for the cut list, transcripts and other documents, and a good answer quietly refreshes the kept copy; sound and video of kept clips always come from the device. A cut list that is not kept gets none of this beyond the last copy seen.

What needs the server: the assistant (the edit chat refuses offline and never keeps a message for later), sending a cut to Resolve or bringing changes back from it, work on the studio's other computers, opening or closing an episode, and sound or search for a cut list not kept on the device.

No background download, check or save holds the page up for longer than one frame: typing, playback and scrolling stay smooth throughout.

### Edits are kept on this device until the server has them, and the editor says when the device will not keep them

{{28-080}}

- Exact: yes

### An edit made offline is the same edit it would have been online

- Every edit can be made offline, undo included: undo takes back the last edit not yet sent.
- An edit made offline lands on exactly the frames, gaps and leading black the same edit made online would give.
- Where the device cannot know an edit's result until the server has it (a card's final words or span), the card is visibly marked as waiting for the server, with no numbers drawn on it rather than guessed ones. The On this device panel lists every waiting edit under "N edits waiting to sync", each as "<edit> · waiting for the server".
- An edit the editor refuses while offline is shown as refused at once and is never queued.
- Each piece of a cut split offline has its own name, the same every time it is sent, and on reconnecting each is found by the stretch of the clip it covers. Any number of edits made offline on one cut land correctly, and a cut renamed meanwhile is found again by its clip and span.
- If an edit made offline cannot be stored on the device, the editor says so at once and the edit is not shown as saved.
- Losing or regaining the server never shows an older state than the one on screen: an older revision never replaces a newer one, a kept copy is replaced only by a state of the same cut list and never by an empty one, and a copy that has been emptied says so.
- Waiting edits are sent when the connection returns, whether or not their cut list is open.

### When the cut list moved on while edits waited, the editor asks once whether to keep them

On reconnecting, the edits that waited on this device are applied in the order they were made, on top of the cut list as it now is, and each lands exactly once. If nobody else changed the cut list meanwhile, they simply land. If others changed what a waiting edit touches, the waiting edits stop at that edit before it is sent, and the editor offers on it:

- a button "Keep mine" ("send this edit anyway, on top of what the server now has"): that edit is sent and the rest carry on after it;
- a button "Drop mine" ("throw this edit away and keep what the server has");
- when more than one edit is held up, a button "Keep all mine", which sends every held edit in one answer, so the editor never has to ask edit by edit.

Every edit that lands is sent once only. Every edit that could not be made is listed under "N edits could not be made and were dropped", each with its reason, and the rest carry on: one refused edit never holds up the others. Nothing is laid over the others' changes without the person's say, and a copy of the waiting edits can be saved as a file before any is dropped.

### Offline, a standing toast tells the person to keep editing

{{29-015}}

- Exact: yes

### Each change between live and offline is announced once

When the server stops answering, the editor says once "server unreachable: editing the offline copy, edits will sync when it is back". When it answers again, the editor says once "server back: live cut list", followed by ", syncing N edits" when edits are waiting. The pill changes at the same moment.

### Inserting still works when the server cannot be reached

- When the server does not answer (offline, no answer, or while it restarts), a selection or pick with its own timing is placed on the page itself by the same rules (12 frames of handle, held off neighbouring speech, words under the span), using the clip's word timings fetched when the transcript opened (waited for up to 5 s if still arriving) or the lane's. When the browser reports it is offline, it does not try the server first.
- Only when the device holds no word timing for that clip and no transcript to place it from (see the next behaviour): "<error>; this selection has no timing of its own, so it needs the server to place it". If the timings never reached the page: "<error>; and the word timings of this clip did not reach the page before it went - reopen the transcript once it is back".
- Messages: "the server did not answer - check the connection and try again"; a refusal: the server's own error text or "the server refused it (<status>)"; "the server sent something that is not an answer".

- Exact: yes

### Any paragraph the transcript panel shows can be inserted offline, placed approximately and trimmed when it syncs

Offline, a paragraph or text with no timing of its own is placed from the transcript and word timing kept on the device, within 12 frames of where the server would place it. Where its edges cannot be found exactly, the cut is made a little wider than the words and the editor says "that paragraph has no word timing in this copy, so the cut covers a little more than the words: the server trims it to them when this syncs". When the edit reaches the server, the cut is trimmed to the words.

### The English already seen stays on the device, so a reload offline still shows it

The English and clip languages are kept on the device per cut list: the last 12 cut lists, 6000 lines each, 600 clip languages; lines over 8000 characters are not kept. Saved about a second after the English changes, on leaving the cut list, and when the page is hidden. On opening a cut list, what is on the device fills whatever the server has not yet answered. If the device's storage fails, this simply stops.

- Exact: yes

### A person can choose to work offline even with the server up

One switch, remembered on this device and surviving a restart. While on: nothing goes to the server and nothing comes from it, exactly as with no network; the editor shows itself offline and keeps every edit on the device; only what is kept on the device is served, and no background top-up runs. Inside the Windows and Android apps the app follows the same switch, and the next cut list opened starts offline. Turning it off reconnects, sends the waiting edits and, if needed, works out the download sizes again.

- In the On this device panel: a "Work offline" switch, with its sentence: "Nothing goes to the server while this is on, even with a network. Edits wait on this device." / "On: nothing goes to the server. Edits wait here until you switch this off."
- In the episode list: "work offline" (explanation: "Use the cut lists downloaded on this device even with the server up, as on a plane. Nothing goes to the server until you go back online.") and, while on, "go back online".
- On the app's settings page, section **WORK OFFLINE**: "Use what is on this device even with the server up, as on a plane. Nothing goes to the server; edits wait here until you switch back." Button **Work offline** / **Go back online**. Messages: "working offline: the app will not contact the server", "back online: the server answers", "back online, but the server did not answer".
- A gold "Offline" badge sits beside the header crumb while it is on (tooltip "Working offline by choice: open the offline settings"); a click opens the On this device panel. On a phone the badge is icon-only, 44 px.

- Who: anyone, for their own device.
- Ways in: the On this device panel, the episode list, the app's settings page in the Windows and Android apps.
- Setting: Work offline. Does: stops every exchange with the server on this device, as on a plane, keeping edits on the device until switched off. Default: off. Who: anyone, for their own device. Applies to: a computer. Search words: work offline, plane mode, no network, offline by choice.
- Phone and desk: the header badge is icon-only on a phone.
- Exact: yes

### The episode list shows which cut lists are kept on this device and opens them with no network

For each episode the list shows whether a cut list of it is kept on this device:

- "downloaded" (explanation: "A cut list of this episode is saved on this device and opens with no network.") with one "open <file>" button per kept cut list; its explanation names the file and "N edit(s) wait to sync" when there are unsent edits.
- "downloaded, page not saved" (explanation: "...open the episode once with a connection.") with no button, when the cut list is kept but the editor itself is not yet saved on the device.

An "on this device" list at the top, newest first, reads "N cut list(s) open offline" and per copy "<episode>: <file>", the number of cuts, "N edit(s) waiting to sync", "saved <local date/time>", and either "its episode is not in this list" or "the episode page is not saved: open the episode once with a connection". It is shown only when at least one copy exists. Opening a copy opens the editor on it; online, it opens the episode the ordinary way. Kept cut lists are matched to their episodes by where they came from. Visiting the list with a connection saves what the next launch needs to work with no network.

Offline, the list shows an "offline" warning:

- not by choice: "The server cannot be reached. This is the episode list as of <date/time or 'your last visit'>. Cut lists marked downloaded open from this device and sync when the server is back. Opening or closing anything else needs the server." with a "try the server again" link.
- by choice: "You are working offline by choice. Cut lists marked downloaded open from this device, and their edits wait here until you go back online. Opening or closing anything else needs the server." with "go back online".

Every open and close button is then unavailable, explained "Needs the server, which cannot be reached."

### The On this device panel keeps a cut list on a device so it opens, edits and plays with no network

{{33-046}}

Any cut list of any episode can be kept this way, and several can be kept side by side.

- Ways in: the toolbar's On this device button, the command palette entry, Keep on a cut list in the projects sheet, the "Offline" button on the list of cut lists, the header's gold "Offline" badge while working offline.
- Name and search words: On this device: offline, download, storage, keep, device.
- Phone and desk: a centred dialog on a desk, a bottom sheet on a phone or touch screen.
- Exact: yes

### The panel shows whether the open cut list is on this device, how big each part is, and how it will be kept

{{33-047}}

Two more switches set how the cut list is kept (disabled while keeping; each change works the sizes out again; on a list already kept they start as that copy was made, and a change offers to keep it again that way):

- "Whole clips": "Keeps every clip whole, so you can insert from the transcripts offline. Larger." Off by default: then only the audio under every cut and shelf item is kept, with 10 s of handle each side, joined where they meet and kept within the clip.
- "Smaller audio": "Half the size again. Speech stays clear; music loses its top end."

An expander "Size of each clip" shows a table of clip, audio size ("no audio") and video size. Sizes are written like "830 KB", "212 MB", "1.4 GB".

Working out the sizes starts no work on the server: missing audio or preview video is made only once a keep is actually asked for. Where this browser cannot keep anything for this address at all, the panel says so in one sentence instead of offering a keep that cannot work.

- Setting: Include video. Does: keeps each clip's preview video on the device too, so the video window plays offline with seeking. Default: on. Who: anyone, for their own browser. Applies to: a computer. Search words: offline video, keep video, include video, download size.
- Exact: yes

### Keeping a cut list shows progress and says plainly how it ended

{{33-048}}

- Exact: yes

### A keep that will not fit is refused before it starts, naming both sizes

Before a keep starts, a device without room for it is refused with both sizes: "this download is <size> and this browser has <size> left: untick some audio, or remove a copy you are not using". A keep the server interrupts by asking for a new sign-in stops and says so. Nothing that holds edits not yet sent is ever removed to make room without asking.

### What a kept cut list holds

A kept cut list holds the cut list itself; for every clip used in the cut or on the shelf, its audio (whole, or the stretches under the cuts with their handles), its waveform, its word timings and, unless video is turned off, its preview video (typically 80 to 350 MB per clip); every transcript of the episode with its English, those the cut uses first; and the episode's other documents the editor needs, with the episode list, so switching between kept cut lists works offline. Media is kept per episode, so two kept cut lists of one episode share one copy. Audio is kept smaller than the server's, and Smaller audio halves it again. Sizes shown for audio, video and waveforms are exact; documents are estimated. A clip with no audio on the server, or audio in a kind the offline player cannot use, is listed as having no audio offline; it still plays online. A copy is complete only when everything it needs is on the device and every clip had audio.

### Bringing a kept copy up to date fetches only what changed and says what it found

Audio, waveforms and video already on the device are skipped when unchanged; a clip re-made on the server (a replaced recording, for example) is recognised by more than its size, fetched again with its waveform, and named. Documents are always checked and replaced when they changed. Audio and documents come first and preview videos last, so a keep stopped part-way leaves a list that plays. An interrupted download picks up where it stopped when the part held belongs to the same source, and otherwise starts that file again; every file is checked for size and content when it lands, and one that arrives short or wrong is fetched once more. A busy server is waited out for a few seconds before it counts as a failure. After a complete run, files of clips the list no longer uses are removed from the device, but only those no other kept list uses, so updating one episode's copy never touches another's.

A kept list shows "On this device" or "Partly on this device", its size and "brought up to date <when>"; in the list of kept cut lists each row reads "up to date <when>" or "part <when>". While an update checks, it reads "checking the downloaded media against the server...", and afterwards it reports what it found: "all media up to date (N files) · checked <time>"; "N files changed on the server and were dropped: ..."; "N files are no longer on this device: ..."; "no media files are downloaded on this device"; or, when the server could not be reached, "could not check: <why>. Last checked <time>" ("Not checked yet" before the first check).

### Kept cut lists are topped up quietly in the background

About 20 seconds after the editor opens and then every 10 minutes, while the editor is connected and not set to work offline, every kept list on the device is brought up to date quietly (the open one first), fetching only what changed. Not in a browser that can keep nothing. A top-up never interrupts the person; what it found, and a top-up that failed, show in the On this device panel with the time of the last check.

### A kept cut list can be removed from the device without touching the server

{{33-049}}

- Exact: yes

### Kept here lists every cut list kept on the device and the space used

{{33-050}}

- Exact: yes

### The panel says where things are kept and whether they will stay

{{33-051}}

What a device keeps lives in one of three places, chosen by itself: inside the Windows or Android app, real files in the app's project folder on disk (shown as "The Windows app's project folder" / "The Android app's projects folder"); otherwise in the browser's own storage, if it really works there (a private window that refuses falls through), shown as "This browser"; otherwise nowhere: "Nowhere (this browser keeps nothing)". Removing one kept cut list deletes only its own files, never another page's or another list's.

- Exact: yes

### A copy of the waiting edits can be saved to a file and restored from it

{{32-033}}

- Ways in: the On this device panel, while a cut list is open.
- Exact: yes

### Waiting edits save themselves to a file without being asked

While edits are waiting on a device, a copy of them saves itself to a file within seconds of an edit, at most once a minute and always including the last edit. Where the browser lets a page keep one file it chose once up to date, the copy overwrites that one file with no question at all, and the tick box in the On this device panel reads "keep a rescue copy of your unsynced edits up to date as you work". Elsewhere the tick box reads "a copy of your unsynced edits is saved to Downloads as you work", and the line under it says "this browser cannot keep one file up to date, so a copy goes to your Downloads folder: at most one every ten minutes, and one the moment the server goes away." On iPhone and iPad it is off by default, with the reason "on an iPhone or an iPad this browser asks before every download, so it is off here unless you turn it on. Save a copy is the one-tap way to keep one."; closing the share sheet there is not an error. The file is the same kind of copy that "Save a copy" makes, and restoring it never applies an edit twice: edits are added once each, oldest first, a file of another cut list is refused naming both lists, and the editor says how many it added.

- Setting: Save waiting edits to a file. Does: keeps a copy of edits not yet on the server in one file in Downloads, overwritten as they change. Default: on, off on iPhone and iPad. Who: anyone, for their own device. Applies to: a computer. Search words: rescue copy, backup edits, unsent edits file, save copy.
- Phone and desk: off by default on iPhone and iPad.

### Timeline Cards has its own apps for Windows and Android that show the editor from the studio's server

{{33-088}}

Inside the apps, the editor keeps several devices in step exactly as it does in a browser, and opens from the dashboard's own address for the editor.

- Name and search words: the Timeline Cards app: Windows app, Android app, desktop app, phone app.
- Exact: yes

### The apps notice within seconds that the server is gone and work offline

The app checks whether the server answers with a short check of about 3 seconds; while it does not, it checks again every 5 seconds. Once the server is found to be down, the editor sees itself as offline at once and works from what the device keeps; audio and video are still really asked for. Every page that opens with a connection is saved on the device as its newest copy (never data, media or the sign-in pages). While the server cannot be reached, a saved page opens marked as an offline copy, and a page never saved shows the offline page below.

### The offline page explains that a page not yet opened online cannot open offline

{{33-090}}

- Exact: yes

### The app's settings page works with no network and sets the server address

{{33-091}}

- Setting: Address of the Timeline Cards page. Does: sets which studio server the app shows; changing it keeps everything already kept on the device. Default: the studio's own Timeline Cards address. Who: anyone using the app, on that device. Applies to: a computer. Search words: server address, app settings, connect app, Timeline Cards address.
- Name and search words: App settings and status: app settings, server address, app status, offline app.
- Exact: yes

### The settings page shows the app's status

{{33-093}}

- Exact: yes

### In the apps, cut lists that are opened are kept on the device by themselves

{{33-094}}

When a background top-up runs, the cut list open at that moment is kept on the device even if it was never kept by hand, so every clip's audio of the open cut list is on the device and skipping between clips with no connection starts at once. In a browser, media is kept only for a cut list the person kept.

- Setting: Keep cut lists I open on this device. Does: in the apps, keeps every cut list opened with the server up on the device, topping it up every ten minutes. Default: on. Who: anyone using the app, on that device. Applies to: a computer. Search words: keep automatically, auto download, offline copy, keep on device.
- Exact: yes

### In the Windows and Android apps, kept cut lists are real files in a folder the person can open and move

{{33-052}}

Inside the folder, each episode has a folder and each cut list a folder within it; folder names are made safe for Windows (forbidden characters become "_", trailing dots and spaces removed, at most 120 characters, reserved names such as CON get a leading "_"), two lists landing on one name get " (2)", " (3)", and anything that is not a cut list goes under "Other". Clip files are named after the clip. A kept file is never left half-written. An episode can be given a folder of its own on a computer, chosen there. Removing a kept list deletes its folder, and an episode folder left empty goes too.

The same change of folder, with the same move-or-leave question, is also on the app's settings page, section **PROJECT FOLDER**: the folder and "N cut lists (size), <free> free"; **Open folder**; a "Move it to (the whole path)" field (placeholder `D:\Timeline Cards`, Enter submits) and **Use this folder**; the same folder changes nothing.

- Ways in: the On this device panel, the app's settings page.
- Setting: Project folder. Does: chooses the folder where the app keeps cut lists as files, moving those already kept or leaving them, as the person says. Default: Documents, "Timeline Cards" on Windows, the app's own "Timeline Cards" folder on Android. Who: anyone using the app, on that computer. Applies to: a computer. Search words: projects folder, where kept, move folder, offline files.
- Exact: yes

### On Android, Open folder opens the projects folder

On Android, **Open folder** opens the projects folder in the phone's file manager; where Android gives the app no way to do that, the button is not offered.

- Phone and desk: on Android only.

### The Windows app installs per person or runs portable, and runs once

The Windows app comes as a one-click installer for the signed-in person of the computer and as a portable program, for 64-bit Windows. Only one copy runs: a second launch brings the existing window forward and restores it. If it cannot start because another program on the computer is in its way, it says so, asks for that program to be closed, and quits.

- Windows and macOS: there is a Windows app; on a Mac the editor is used in a browser.

### The Windows app's window, links, permissions and downloads

{{33-098}}

- Exact: yes

### The Android app needs Android 10 or newer and asks for little

The Android app runs on Android 10 or newer. It asks to use the internet, to vibrate, and to install apps (for its own updates); it asks for no storage permission (kept files go in the app's own folder; downloads go through the system's Downloads). Android's own app backup is turned off for it.

### The Android Back gesture goes back in the page, then offers a small menu

{{33-104}}

- Exact: yes

### On Android, downloads land in Downloads/Timeline Cards, one file per name

{{33-105}}

- Exact: yes

#### Lessons

- Met: CE1-133, CE1-135, CE2-101, CE2-102, CE2-105, CE2-106, CE2-107, CE2-108, CE1-136, CE1-137, CE1-138, CE2-110, CE2-111, CE2-118, CE2-124, CE2-128, CE2-129, CE2-130, CE2-132, CE3-066, CE3-067, CE3-068, CE3-074, CE3-078, CE1-139, CE1-140, CE1-141, CE1-142, CE1-143, CE1-144, CE2-112, CE2-113, CE2-114, CE2-115, CE2-116, CE2-117, CE2-119, CE2-120, CE2-121, CE2-122, CE2-123, CE2-125, CE2-126, CE2-127, CE2-131, CE3-069, CE3-070, CE3-071, CE3-072, CE3-073, CE3-075, CE3-076, CE3-077.
- Tied to an arrangement: CE1-134, CE1-145, CE1-146, CE2-103, CE2-104, CE2-133, CE2-134 (the promises are in "The editor opens with no network once it has been opened on that device", "Several people and devices edit one cut list live, and every edit is saved before it counts", "Timeline Cards has its own apps for Windows and Android that show the editor from the studio's server" and "The panel says where things are kept and whether they will stay").
