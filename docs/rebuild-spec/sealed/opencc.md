# Sealed notes: opencc

SEALED. Not part of the pack. Released to the rebuild only after its own committed design names this tool. 2 notes.

### CFI-S17: Every Simplified-to-Traditional conversion table turns 台 into 臺.
- Why: The mapping sits in the base table every mode starts from, so even the Taiwan modes rewrite 台灣 as 臺灣, on already-Traditional text too.
- Must: After conversion 臺 is put back to 台 in words, sentences and transcripts alike, and the conversion applied is recorded.
- Tool: OpenCC (s2t, s2tw, s2twp)
- Where it bit: Timeline Cards: footage in, ready to cut

### CFI-S18: The Taiwan phrasing rules fire only on whole phrases.
- Why: 類型 becomes 型別 and 數據 becomes 資料 as words, but 類 and 型 sent separately come back unchanged, so per-word conversion broke 398 words.
- Must: Conversion runs over the joined text and is split back onto the timed words, never one word at a time.
- Tool: OpenCC s2twp phrase conversion
- Where it bit: Timeline Cards: footage in, ready to cut
