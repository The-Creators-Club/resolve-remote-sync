# Sealed notes: chinese-word-segmenters

SEALED. Not part of the pack. Released to the rebuild only after its own committed design names this tool. 1 notes.

### CFI-S19: Ready-made Chinese word splitters break exactly the names that matter.
- Why: One splitter gave 放生 | 態相機 and 颱 | 風; the other's Traditional model gave 林 | 保署.
- Must: Any word grouping is checked on the studio's Traditional Chinese interviews, names and abbreviations included, before it is trusted.
- Tool: jieba and Stanza zh-hant word segmentation
- Where it bit: Timeline Cards: footage in, ready to cut
