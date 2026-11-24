# Joins aimed at cards-editor-3

## Checked

- J1 | fine
- J2 | F1
- J3 | fine
- J4 | fine
- J5 | fine
- J6 | fine
- J7 | F2

## Findings

### F1: the transcript's sentence cursor on the English line inserts a whole paragraph, where an English selection here stands for exactly the original words it translates
- Kind: contradiction
- From: cards-editor-1 / While the transcript has the keyboard, its own keys act on it and the lane's and cards' keys do not
- Here: The English a cut shows / Selecting part of the English line in a transcript selects the original words it translates (30-028) and When an insert comes from an English selection that lined up word for word the new cut keeps that English
- From says: "The cursor is on the English line: an English sentence inserts its whole paragraph unless it has its own timings."
- Here says: "selecting part of the English line stands for the original words that English translates. From then on it acts exactly as if those original words had been selected" and "When the English did not line up word for word, the cut takes the whole original sentence, marked approximate"
- Settled by: OWNER_REQUIREMENTS.md section 6, Footage in: "times every word, so that any part of the English stands for exact words of the original" (the X message is also marked Exact under section 4, so the owner must say whether that sentence may change: should an English sentence chosen with the transcript's cursor insert just the original words it translates, like an English text selection, rather than its whole paragraph?)
- Fix: cards-editor-1 should say the cursor's English sentence inserts the original words it lines up with (the whole original sentence, marked approximate, when it has not lined up), with its X message reworded to match, and cards-editor-3 should say that the sentence cursor on the English line follows the same rule as an English text selection.

### F2: the whole product still names a "search inside one transcript" with a fixed strength, a search the owner cut and this piece does not have
- Kind: contradiction
- From: whole-product / A person picks how strong an assistant answers, where offered
- Here: Search and the transcript panel (the search sheet is the only assistant search; a one-person scope uses the sheet's own Model picker)
- From says: "Summaries, the montage builder and search inside one transcript always use the fastest."
- Here says: "a person searches only that person's interview transcripts" and "\"Model\" (assistant kinds only): three strengths of the assistant ... fastest (default), stronger, most capable, remembered per device"
- Settled by: decision cards-editor-3-Q8, "Answered by the owner 2026-11-24: A, only the search sheet; the search inside one transcript and the search across the montage clips are cut"
- Fix: whole-product should drop "search inside one transcript" from its list of fixed-strength features (a one-person search is the search sheet's scope and uses the sheet's chosen strength).
