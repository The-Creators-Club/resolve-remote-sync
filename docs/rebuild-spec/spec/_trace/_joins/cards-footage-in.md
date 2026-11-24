# Joins aimed at cards-footage-in

## Checked

- J1 | F1
- J2 | F2
- J3 | fine
- J4 | fine
- J5 | F3
- J6 | F4
- J7 | F5
- J8 | F6
- J9 | F7
- J10 | F8, F9
- J11 | fine
- J12 | F4
- J13 | F10
- J14 | F11
- J15 | F12, F13
- J16 | F14
- J17 | F14
- J18 | F15, F16
- J19 | fine

## Findings

### F1: With the assistant off, footage-in breaks paragraphs at every pause, while the board says every paragraph is at least two sentences broken at sentence ends
- Kind: contradiction
- From: cards-board / A card is a paragraph, a note, or a paragraph from another episode
- Here: The product breaks each transcript into paragraphs by meaning
- From says: "A paragraph is at least two sentences and at most a short passage, broken at sentence boundaries"
- Here says: "When the assistant is off: paragraphs break at every pause of 1.2 seconds or more, within the same length limits"
- Settled by: CFI-075 (ruling): "Transcripts split into cards of at least two sentences, merging shorter fragments into a neighbour and keeping the first one's reference."
- Fix: footage-in's assistant-off rule should still merge fragments shorter than two sentences into a neighbour (breaking at a pause only at a sentence end), and the board should limit its two-sentence floor to answer paragraphs, since a question is a paragraph of its own.

### F2: The board's "speaker" of a card is the interviewee an interview is filed under, but it points to footage-in's per-word speaker labels for the override
- Kind: differs
- From: cards-board / A card's speaker is the interviewee
- Here: The product decides which person each recording belongs to; The product decides who is speaking
- From says: "who is speaking is set by hand in Timeline Cards: footage in, ready to cut (Running on its own, with a hand on every decision), and the board follows it"
- Here says: "a person can file an interview under another person" (filing) and "a person can name each speaker, merge two speakers, and set the speaker of any line" (who is speaking)
- Settled by: the owner must say: is the person a card is credited to the interviewee its interview is filed under, or whoever is marked as speaking its words?
- Fix: cards-board's by-hand line should name footage-in's "The product decides which person each recording belongs to" (filing an interview under a person) if the answer is the interviewee, as its own first sentence implies.

### F3: The editor re-spells a cut's words by comparing letters with the paragraph, which footage-in and the owner rule out
- Kind: contradiction
- From: cards-editor-2 / A cut's words always follow its span, on every device
- Here: One file per interview holds the whole transcript
- From says: "wherever the transcript's paragraph lines up with the spoken words (letters compared, Simplified and Traditional alike, at least 40 % matching); filler the transcript left out is dropped. Elsewhere the speech-to-text's spelling stays."
- Here says: "These are tied to each other directly and never found again by matching text, so correcting a word can never loosen its timing or its translation."
- Settled by: OWNER_REQUIREMENTS section 6: "They are tied to each other directly and never found again by matching text, so correcting a word cannot loosen its timing or its translation."
- Fix: cards-editor-2 should take a cut's words straight from the transcript's timed words, which already carry the transcript's own spelling (footage-in: "the words stay in the transcript's own wording and characters"), with no letter comparison and no speech-to-text fallback spelling.

### F4: The editor gives every clip its own small picture when it arrives; footage-in makes one preview per interview, after lining up, and says a non-multicam recording gets none
- Kind: contradiction
- From: cards-editor-2 / Every clip is made ready to play without anyone asking (also cards-editor-4 / Keeping a cut list shows progress and says plainly how it ended, whose keep fetches "Video: <clip>" per clip)
- Here: Every interview gets a small preview exactly as long as its sound; A preview that cannot be made never stops anything else
- From says: "Each clip's small playback copies (its light sound, its small picture and its waveform) are made by themselves when the clip arrives in the episode"
- Here says: "Beside each interview's sound the product makes a small preview" and "Every recording without a preview gets one plain reason (not a multicam, its sound check failed"
- Settled by: the owner must say: does every clip dropped into an episode (a single camera clip, a montage clip) get its own small picture to play in the editor, or only each interview's multicam?
- Fix: cards-footage-in should say which clips get a small picture and when (it already says montage clips can be "previewed"), and cards-editor-2 should match it.

### F5: Side-file notes brought into cut lists are said to be footage-in's, which says nothing about them
- Kind: missing
- From: cards-editor-2 / A note on a card or a gap is kept in the cut list as an edit like any other
- Here: nowhere
- From says: "Notes the studio kept in side files beside earlier cut lists are brought into their cut lists once, when the studio's existing work is carried over."
- Here says: nothing
- Settled by: OWNER_REQUIREMENTS section 7: "The list is in the carry-over companion to this specification."
- Fix: cards-editor-2's join should point to the carry-over companion, not to footage-in's "Bringing the studio's existing transcripts in once"; footage-in needs no change.

### F6: A dropped file is looked for only under the episode folder in the editor, but anywhere on the studio's storage in footage-in
- Kind: contradiction
- From: cards-editor-3 / Dropping media files on the panel hands the clips to footage in and lists each one in the intake
- Here: A dropped file is found where it already is
- From says: "One is / N are not in [the episode's media] yet: put it/them under the episode folder and drop again."
- Here says: "A dropped recording is found on the studio's storage by its name and size and used where it is"
- Settled by: OWNER_REQUIREMENTS section 6: "Nothing outside the product is needed: no separate notes program, no folder a person must keep in a certain shape"; also CFI-100 (given, weaker): "Dropped media is found on the NAS by name and size".
- Fix: cards-editor-3 should look for a dropped file across the studio's storage and tell a person to put a missing one on the studio's storage, as footage-in says.

### F7: The editor finds which paragraphs a cut crosses by matching its letters, not through the transcript's own ties
- Kind: contradiction
- From: cards-editor-3 / A trimmed or split cut's English is worked out from the line-ups and marked approximate only when it truly is
- Here: One file per interview holds the whole transcript
- From says: "A cut across paragraphs: its letters are matched against the paragraphs (its head may be the tail of one, its end the head of another)."
- Here says: "These are tied to each other directly and never found again by matching text"
- Settled by: OWNER_REQUIREMENTS section 6: "They are tied to each other directly and never found again by matching text, so correcting a word cannot loosen its timing or its translation."
- Fix: cards-editor-3 should take the paragraphs a cut crosses, and the words no paragraph holds, from the ties each timed word has to its paragraph, with no letter matching.

### F8: The editor says a waiting English selection falls back to its sentence; footage-in says the sentence only when the sentences pair up, else the whole paragraph
- Kind: contradiction
- From: cards-editor-3 / A settings row shows how far the English is lined up with the original
- Here: What a selection of English stands for
- From says: "an English selection waiting on it falls back to the whole original sentence, marked approximate"
- Here says: "the selection stands for the whole original sentence or sentences it is in, when the English and the original have the same number of sentences (more than one); otherwise for the whole original paragraph"
- Settled by: the owner must say: when the English cannot yet be linked word by word, does a selected bit of English stand for its sentence even when the English and the original do not have the same number of sentences, or for the whole paragraph then?
- Fix: cards-editor-3 should say the selection "falls back to Approximate" and point to footage-in's "What a selection of English stands for" instead of restating the rule (its assistant-off line too).

### F9: Two sentences for lining up being unavailable, with no word on whether they are one message
- Kind: differs
- From: cards-editor-3 / A settings row shows how far the English is lined up with the original
- Here: Footage-in works most urgent first, within the site's daily budget
- From says: "\"Not available on this server.\""
- Here says: "lining up stands still with \"Assistant is not available on this server (<why>)\""
- Settled by: OWNER_REQUIREMENTS section 4: "Where this specification marks a passage `Exact`, it is to be built as written." (the editor's row is marked Exact)
- Fix: cards-footage-in should say where its sentence is shown (to a person waiting on a selection) so a builder knows it is a second place and not the settings row, or use the row's wording if it is the same place.

### F10: The hand-over builds an interview's multicam in Resolve by itself, which footage-in says Resolve's scripting cannot do
- Kind: contradiction
- From: cards-to-resolve-and-exports / Clips the project lacks are brought into it before the cut is placed
- Here: The interview's multicam is ready for the editing program without one being open
- From says: "An interview whose multicam is not yet in the project gets it, built in Resolve from the angles and the line-up Timeline Cards made when the footage came in"
- Here says: "Resolve's scripting cannot create a multicam clip, cannot reach a multicam's angles and cannot set a transcription language. Nothing in getting footage ready depends on any of these, and any step left to a person inside Resolve is named exactly."
- Settled by: CFI-020 (given, weaker than a ruling): "Multicam creation never assumes Resolve offers a scripted way, and any step left to a person in Resolve is named exactly."
- Fix: cards-to-resolve-and-exports should say how the multicam reaches Resolve without a scripted creation, or name exactly the step a person takes there and show it in the dry run.

### F11: The hand-over fixes an unknown clip rate at 29.97 drop-frame; footage-in makes that default an admin's site setting
- Kind: contradiction
- From: cards-to-resolve-and-exports / Which frame rate a clip is taken to have
- Here: Each interview's frame rate and drop-frame are chosen on its own
- From says: "A clip of unknown rate is taken as 29.97 drop-frame."
- Here says: "Setting: Frame rate when nothing states one. Does: the rate given to a clip or interview whose files state none. Default: 29.97 drop-frame. Who: an admin."
- Settled by: CFI-016 (ruling) for the value: "Timelines and clips with no stated rate default to 29.97 drop-frame"; OWNER_REQUIREMENTS section 1: "one place a setting comes from".
- Fix: cards-to-resolve-and-exports should take an unknown clip's rate from footage-in's "Frame rate when nothing states one" setting (default 29.97 drop-frame).

### F12: Telling speakers apart is always done in footage-in but only on request in a transcription job
- Kind: contradiction
- From: fleet-jobs / A computer transcribes an episode's folder
- Here: The product decides who is speaking
- From says: "can ask for speakers to be told apart"
- Here says: "Every recording, interview or montage clip, has its speakers separated."
- Settled by: the owner must say: is every transcript split by speaker, or only when whoever asks for the transcription asks for it?
- Fix: fleet-jobs should drop the option if every recording is split, or footage-in should say when speakers are not told apart.

### F13: The preview copy plays stereo, is never enlarged and fails with no picture in fleet-jobs; footage-in's preview is mono, 480 lines tall, and sound-only when there is no picture
- Kind: contradiction
- From: fleet-jobs / A small preview copy of a clip is made for Timeline Cards (noticed while checking J15)
- Here: Every interview gets a small preview exactly as long as its sound; Which picture the preview shows
- From says: "A preview copy is at most 480 lines tall, never enlarged, ... and stereo sound." and "A clip with no picture fails as \"no video track\" and is not tried again."
- Here says: "480 lines tall keeping the picture's shape, at the multicam's frame rate, ... mono sound from the camera" and "When no angle has any picture, the preview is sound alone and says plainly that there is no picture."
- Settled by: CFI-023 (given, weaker) for the no-picture case: "its audio-only preview says plainly there is no picture"; for the rest the owner must say: does a preview play its sound in one channel or two, and is a small source enlarged to 480 lines?
- Fix: fleet-jobs should point to footage-in's preview description instead of restating it, after footage-in is settled on mono or stereo and on enlarging.

### F14: Lining up by sound searches an hour either side in footage-in, but the Sorter's matching of the same sound tries whole-hour time zone shifts
- Kind: contradiction
- From: footage-sorter-and-camera-cards-2 / The Sorter proposes where each sound recording belongs (also footage-sorter-and-camera-cards-1 / A recorder's reset clock is corrected from its neighbouring files)
- Here: Every take is lined up by sound to within a frame
- From says: "searched within 20 minutes of where the time estimate expects it" and "When the recorder's clock as read finds nothing, whole-hour time zone shifts are tried in turn (a recorder on Kyiv time against cameras on Taiwan time is 5 hours out)"
- Here says: "First a constant offset for the whole device is searched for, far enough to find a source an hour either side of where its clock places it."
- Settled by: OWNER_REQUIREMENTS section 1: "One way to do each thing"; CFI-001 (given, weaker): "searching far enough to find a source an hour from its file time".
- Fix: both pieces should describe one matching of a recorder's sound to the cameras' with one set of limits, and footage-in's device search should also try whole-hour shifts so a recorder 5 hours out on the same day is still lined up.

### F15: Two different rules for recognising a recording already heard
- Kind: contradiction
- From: footage-sorter-and-camera-cards-2 / Every sound recording is listened to for names and introductions
- Here: A recording already transcribed is not transcribed again
- From says: "a file that moved (same name, size, and length within 1 second) reuses what was heard"
- Here says: "the same size and modified time (to a hundredth of a second), or failing that the same content at its start and end, which also recognises the same file copied elsewhere"
- Settled by: OWNER_REQUIREMENTS section 1: "One way to do each thing"; CFI-063 (situation, weaker): "A re-run skips every clip already transcribed, including the same file copied elsewhere".
- Fix: footage-sorter-and-camera-cards-2 should recognise a recording already heard by footage-in's rule and reuse that recording's one transcript, rather than keep a rule of its own.

### F16: Two different lists of phrases for recognising someone introducing themselves
- Kind: differs
- From: footage-sorter-and-camera-cards-2 / Every sound recording is listened to for names and introductions
- Here: The interview starts at the crew's first question
- From says: "Self-introductions are recognised from \"我是\", \"我叫\", \"這位是\", \"我們今天訪問\", \"my name is\", \"I am called\", and \"we are\" followed by an organisation."
- Here says: "a line that begins 我是, 我叫 or 大家好 after any filler, or \"my name is\", or \"I'm\" or \"I am\" followed within 100 characters by \"and I\"."
- Settled by: the owner must say: should the Footage Sorter and Timeline Cards recognise someone introducing themselves from the same phrases?
- Fix: one piece should hold the list of self-introduction phrases and the other point to it (footage-in's "who introduces themselves and when" on the interview's page uses its own list today).
