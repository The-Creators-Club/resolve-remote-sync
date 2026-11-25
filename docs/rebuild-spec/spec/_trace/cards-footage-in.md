# Trace of cards-footage-in

## Coverage

- 39-071 | Recordings are sorted into cameras and recorders by their names
- 39-074 | Each device's clock is chosen on its own and shown
- 41-006 | One-sided stereo sound is made to play in both ears
- 39-076 | Each interview's frame rate and drop-frame are chosen on its own ; Mixed rates and off-speed clips are reported as soon as they arrive
- 41-005 | Each interview's frame rate and drop-frame are chosen on its own
- 39-016 | left out: ruled out by CFI-049 and CFI-050 (no editing program while footage is processed); the promise is under "Transcripts come only from the product's own speech-to-text"
- 39-072 | The interview's multicam is ready for the editing program without one being open
- 39-085 | The interview's multicam is ready for the editing program without one being open
- 41-004 | Word times count from the interview's own starting timecode
- 39-073 | The product decides which clips are interview takes and says why each other clip was left out
- 39-075 | A day with several interviews is split into sessions
- 39-077 | The product chooses the device every other device is lined up against
- 39-078 | The interview's sound is always the recorder's
- 39-079 | Every take is lined up by sound to within a frame
- 39-080 | The product decides the order of the angles
- 39-081 | Long empty stretches can be shrunk and a single camera laid back to back
- 39-082 | What the interview's multicam holds
- 39-083 | The interview's multicam is ready for the editing program without one being open
- 39-086 | Every take is lined up by sound to within a frame ; Each device's clock is chosen on its own and shown
- 39-087 | A person can line an interview's picture up again ; Every camera piece is checked against the sound along its whole length
- 39-088 | The interview's sound is always the recorder's ; A person can swap in a better recording of the interview's sound
- 41-003 | The product decides which person each recording belongs to
- 41-024 | Which picture the preview shows
- 41-025 | Every camera piece is checked against the sound along its whole length
- 41-028 | The interview starts at the crew's first question
- 41-029 | Each interviewee is given a colour
- 41-015 | A transcription made in the editing program is never the transcript
- 42-026 | Nothing said is missing from a transcript ; A transcription made in the editing program is never the transcript
- 41-008 | The language of every stretch of speech is decided on its own
- 41-009 | Each recording's main language is decided on its own
- 41-014 | Nothing said is missing from a transcript
- 39-017 | A person can transcribe clips from the editor
- 40-034 | What transcribing needs and what a person sees while it runs ; A person can transcribe clips from the editor ; A dropped file is found where it already is
- 41-013 | What transcribing needs and what a person sees while it runs
- 41-010 | Chinese is written in Traditional characters as Taiwan writes it
- 39-036 | Every existing paragraph is placed in its recording
- 40-039 | The studio's existing transcripts are brought in once with every paragraph's address ; The product marks which paragraphs are the interviewer's questions
- 41-011 | One file per interview holds the whole transcript
- 41-016 | The product breaks each transcript into paragraphs by meaning
- 41-017 | Splitting a paragraph never changes a single character of what was said
- 41-018 | The product marks which paragraphs are the interviewer's questions
- 41-019 | The interviewee's words are never altered
- 41-020 | Every paragraph has a permanent address
- 41-021 | Every paragraph not in English gets English
- 41-033 | A person's edits are never lost to an automatic redo
- 42-028 | The product breaks each transcript into paragraphs by meaning
- 42-032 | The interviewee's words are never altered ; Every paragraph not in English gets English
- 30-029 | What a selection of English stands for
- 30-033 | English and original are linked phrase by phrase on their own
- 30-042 | Word links and glosses inside each phrase
- 41-022 | English and original are linked phrase by phrase on their own
- 30-034 | Footage-in works most urgent first, within the site's daily budget
- 39-084 | Every decision is shown and can be set by hand
- 40-010 | Every existing paragraph is placed in its recording
- 40-011 | The studio's existing transcripts are brought in once with every paragraph's address
- 41-001 | Clips dropped in become an interview ready to cut
- 41-002 | Every decision is shown and can be set by hand
- 41-012 | A recording already transcribed is not transcribed again
- 41-040 | Footage-in works whichever computers the studio has
- 42-027 | Nothing said is missing from a transcript
- 42-029 | The product breaks each transcript into paragraphs by meaning
- 42-030 | The product marks which paragraphs are the interviewer's questions
- 42-031 | Off-topic chatter is set apart
- 42-033 | Every paragraph not in English gets English
- 42-034 | One file per interview holds the whole transcript
- 43-040 | The studio's existing transcripts are brought in once with every paragraph's address ; A transcript taken from another episode times and plays from its source
- 43-041 | Every existing paragraph is placed in its recording
- 43-042 | Every existing paragraph is placed in its recording
- 40-032 | left out: ruled out by CFI-050 (no editing program while footage is processed); the promise is under "Clips dropped in become an interview ready to cut"
- 41-007 | Nothing made from a recording can harm it
- 41-023 | Every interview gets a small preview exactly as long as its sound
- 41-026 | A finished preview is checked against the sound
- 41-027 | A preview that cannot be made never stops anything else
- 40-040 | Montage material is downloaded clips with a credit record
- 41-030 | A folder of outside clips becomes searchable transcripts with word times
- 41-031 | A montage clip's transcript is laid out by its pauses ; There is always a readable Markdown copy of each transcript
- 41-032 | The product decides who is speaking

## Questions for the owner

### cards-footage-in-Q1: Should every interview's sound be loudness-levelled on its own, or only a recording a person swaps in?
- Kind: other
- Today: a one-off repair that puts the Zoom recording under every angle also levels it to -23 LUFS (EBU R128) on its own; the normal build does not level anything.
- Options: A: level every interview's sound to -23 LUFS on its own, with a switch to turn it off per interview. B: level only a recording a person swaps in (which your rule on swapping audio requires), and leave the normal interview sound as recorded.
- Recommend: B, because it keeps the recorded sound untouched unless a person acts, and the swap rule already asks for levelling there.
- Changes for a person: with A every interview arrives at one loudness; with B interviews sound as recorded and the editor sets levels later.
- Text assumes: B
- Items: 39-078, 39-088
- Covers: 39-Q11
- Answered by the owner 2026-11-24: B, only a recording a person swaps in is levelled

### cards-footage-in-Q2: When an interview's preview is found to be more than a frame out of sync, what should happen?
- Kind: other
- Today: it is only flagged on the run's report; the preview is used anyway.
- Options: A: keep it, with a warning on the interview and on its cards, and a way to make it again. B: hold it back until it is made again in sync. C: make it again on its own.
- Recommend: A, because a preview is only for watching while cutting and a warning tells the editor what to trust, with no extra machinery.
- Changes for a person: with A the editor sees the preview at once with a warning; with B no picture until fixed; with C it may change under them.
- Text assumes: A
- Items: 41-026
- Covers: 41-Q5
- Answered by the owner 2026-11-24: A, kept with a warning and a way to make it again

### cards-footage-in-Q3: Should one translator make the English for both interviews and montage clips, and which?
- Kind: either-or
- Today: interview English is made by the assistant while paragraphs are made; montage-clip English by a separate translator on the studio's own computer that needs no outside account.
- Options: A: the assistant for both; with the assistant switched off, no English is made on its own and a person can write it. B: a translator on the studio's own computers for both, which keeps working with the assistant off but cannot correct mishearings or transliterate names as well. C: keep both.
- Recommend: A, one way, and the one that can follow your rules (names transliterated, mishearings corrected only in the English).
- Changes for a person: with A, montage English is of the same quality as interview English, and a site with the assistant off gets no English on its own; with B a site with the assistant off still gets English.
- Text assumes: A
- Items: 41-021
- Covers: 41-Q7
- Answered by the owner 2026-11-24: A, the assistant makes all English; with it off, a person writes it

### cards-footage-in-Q4: When no computer with a usable graphics card is free, should transcription wait for one, or run slowly at once on whatever computer can reach the footage?
- Kind: other
- Today: transcription runs on the processor of the computer it was given when its graphics card cannot be used, and says it will be much slower.
- Options: A: wait for a computer with a usable card; run on a processor only when the studio has no such computer, or when a person picks one. B: run at once on any free computer, card or not.
- Recommend: A, because a run on a processor can take many times longer and hold a computer for hours that a card would free in minutes.
- Changes for a person: with A an interview may wait for the card computer to be free; with B it starts sooner but may finish later.
- Text assumes: A
- Items: 41-013, 41-040
- Covers: 41-Q9
- Answered by the owner 2026-11-24: A, wait for a computer with a usable graphics card

### cards-footage-in-Q5: Does your rule that a card holds at least two sentences apply to an interviewer's question and to chatter too?
- Kind: other
- Today: paragraphs are made with one interviewer question each and chatter in small paragraphs of its own, which is often one sentence; your rule says a card is never a single sentence.
- Options: A: the two-sentence floor applies to answer paragraphs; a question stays its own paragraph directly above its answer, and chatter stays apart. B: it applies to every paragraph, so a one-sentence question is joined into its answer and chatter into a neighbour.
- Recommend: A, because a question travels with its answer anyway and chatter is left out of the themes, so both stay findable and separable.
- Changes for a person: with A a question is a small card of its own above its answer; with B the question is the first sentence of the answer's card.
- Text assumes: A
- Items: 42-028, 41-018, 42-031
- Covers:
- Answered by the owner 2026-11-24: A, the two-sentence floor applies to answer paragraphs only

### cards-footage-in-Q6: When someone has edited the readable Markdown copy of a transcript in another program, what should happen when the product writes the copy again?
- Kind: other
- Today: a montage clip's readable transcript that someone edited by hand is never overwritten unless a person asks to redo it; your requirement says the product keeps the copy in step and does not follow changes made to it elsewhere.
- Options: A: set the edited copy aside under a name that says so, write a fresh copy, and tell the person. B: overwrite it. C: stop updating that copy until a person decides.
- Recommend: A, because nothing anyone typed is lost and the copy is still kept in step.
- Changes for a person: with A an edited copy turns up beside the fresh one; with B outside edits vanish; with C the copy goes stale.
- Text assumes: A
- Items: 41-031
- Covers:
- Answered by the owner 2026-11-24: A, an outside-edited copy is set aside before a fresh one is written

### cards-footage-in-Q7: When one drop holds several sessions (gaps of more than 30 minutes), should each session become an interview of its own on its own?
- Kind: other
- Today: building refuses until a person names one session, or asks for all sessions to be laid out together.
- Options: A: each session becomes its own interview on its own, and a person can join sessions. B: the whole drop is one interview, and a person can split it.
- Recommend: A, because a gap of half an hour almost always means another interview, and a join is one act.
- Changes for a person: with A a day of three interviews arrives as three; with B it arrives as one to be split.
- Text assumes: A
- Items: 39-075
- Covers:
- Answered by the owner 2026-11-24: A, each session becomes its own interview

### cards-footage-in-Q8: How close must a device's timecode be to its file dates for the timecode to count as the time of day?
- Kind: differs
- Today: the one-step build accepts timecode as the time of day within 60 seconds of every clip's creation date; the older way accepted it only within 3 seconds, or used each camera's own timecode from its first frame when asked.
- Options: A: within 60 seconds. B: within 3 seconds.
- Recommend: A, because file dates are only good to a second and slightly-off clocks are common, and the sound places every take within a frame afterwards anyway.
- Changes for a person: almost none; with B more cameras are placed by file date before the sound lines them up.
- Text assumes: A
- Items: 39-074, 39-086
- Covers:
- Answered by the owner 2026-11-24: A, within 60 seconds

## Readers' questions and unsettled points

- 30-Q2 | with cards-editor-3
- 39-Q9 | not a question: the text keeps one way, and every choice the older way offered (file dates, timecode, clock alone) is a hand override in it, so a person loses nothing
- 39-Q10 | answered: CFI-035 and CFI-036 (rulings): re-lining picture onto sound and swapping in better sound stay as hand actions on the interview; the one-off forms tied to the editing program go
- 39-Q11 | cards-footage-in-Q1
- 41-Q2 | answered: CFI-006 (the original is kept unaltered)
- 41-Q3 | answered: CFI-029 and CFI-030 (the multicam starts at the first question on its own, and a person can move the start)
- 41-Q4 | answered: the owner's requirements (who is speaking is decided on its own and can be set by hand)
- 41-Q5 | cards-footage-in-Q2
- 41-Q7 | cards-footage-in-Q3
- 41-Q9 | cards-footage-in-Q4
- 42-Q7 | answered: CFI-052 and the owner's requirements (recovered text goes in on its own, marked, and a person can remove it)
- U-30-5 | settled: the items give the setting to anyone who can open the editor, and the text says so
- U-39-7 | settled: the text has one way to transcribe by hand, on a computer picked from a list
- U-41-3 | settled: CFI-058 requires every recording to have word times or say why
- U-41-4 | behind the glass
- U-42-4 | settled: the text states what each check must achieve, from the items and lessons
- U-43-1 | settled: the editing program's subtitle exports carry the project's start timecode, normally 01:00:00:00, and anything brought in is compared in its own time base
- U-43-4 | settled: each interview is filed under its person, and the colour goes with the person, so no name matching is needed

## Still unsettled

## Conflicts between an item and a lesson

- CFI-001 | 39-079 | the item searches a device's offset within 15 minutes either way; the lesson asks for a search that finds a source an hour away; wrote an hour.
- CFI-006 | 41-006 | the item rewrites the recording in place (automatically without keeping the stereo original); the lesson says the original is kept unaltered; wrote that the original is never changed and the one-channel sound is a made file.
- CFI-024 | 41-006 | the item and CFI-006 count a channel under -30 dBFS as empty; CFI-024 speaks of a channel above about -60 dBFS; wrote -30 dBFS as the default of a site setting.
- CFI-069 | 42-032 | the item says Chinese characters are kept as transcribed and never converted; the ruling asks for Traditional with Taiwan phrasing; wrote the ruling (conversion when the transcript is made, never a correction afterwards).
- CFI-086 | 30-033, 30-042 | the items make a failed answer final for that text; the lesson retries once and shows a reason after two failures; wrote the lesson.
- CFI-107 | 43-042 | the item ends an unplaced paragraph at "text not found"; the lesson keeps it, lists it and shows the closest stretch with its likeness; wrote the lesson.
- CFI-109 | 43-040, 40-011 | the items tie a transcript to a clip by a word-for-word name likeness or a content vote; the lesson ties only by explicit pointer or exact name; wrote the lesson, with the content vote offered for a person to accept.
- CFI-049, CFI-050 | 40-010, 43-041, 39-016, 40-032 | the items use the editing program's transcription as a word source and render sound from it; the rulings forbid both; wrote that the editing program's transcription is never the transcript and is used only to help place existing paragraphs when they are brought in.
- CFI-092 | 39-017 | the item needs the computer running the editing program with it reachable; the ruling has a person pick any computer from a list; wrote the ruling.
- CFI-028, owner's requirements | 41-003 | the lesson wants a borderline name confirmed before anything is filed; the requirements say no step waits for a person; wrote that only the filing waits, and everything not depending on who it is carries on.
- CFI-013 | 39-076 | the older layout refused mixed rates; the lesson reports them and keeps them in sync; wrote the lesson.
- owner's requirements | 39-075 | the item refuses to build until a session is named; the requirements want no step waiting; wrote each session as its own interview (Q7).
- owner's requirements | 41-031 | the item never overwrites a hand-edited readable transcript; the requirements say the product writes the copy and keeps it in step; wrote the copy set aside before rewriting (Q6).
- owner's requirements | 41-033 | the item keeps one backup; the requirements say a hand-set value is never overwritten; wrote that hand-set values survive and every earlier version is kept.

## New in this text

- Recordings are sorted into cameras and recorders by their names | a person can move a recording to another device, join, split and rename devices
- A day with several interviews is split into sessions | each session becomes an interview of its own on its own; a person can join sessions and split one at a time they choose
- The product decides which person each recording belongs to | a likely name match is asked as "Is this <person>?" while other work carries on; a recording can be split into two interviews
- The interview's names are chosen on its own | the names of the interview, multicam and transcript are decided on their own and each can be renamed by hand
- The interview's sound is always the recorder's | loose recordings are matched by content and a person accepts a match or names the sound device on the interview's page, which is recorded and shown
- Every take is lined up by sound to within a frame | a raw file with no proxy waits for one instead of refusing; a person can move one take and accept an unverified angle
- Every camera piece is checked against the sound along its whole length | a person can move a piece by a number of frames
- A person can line an interview's picture up again | a hand action on the interview's page instead of a one-off repair run in the editing program
- A person can swap in a better recording of the interview's sound | a hand action on the interview's page, written from the rulings
- Long empty stretches can be shrunk and a single camera laid back to back | laying a single stop-start camera back to back, from CFI-034
- Which picture the preview shows | a person can choose the angle the preview shows
- Each interviewee is given a colour | a person can pick another colour
- The language of every stretch of speech is decided on its own | a person can set the language of one stretch
- Each recording's main language is decided on its own | a person can set the main language
- Each speaker is transcribed in their own language, and an interpreter can be left out | marking a speaker as the interpreter drops their lines, from CFI-057
- Nothing said is missing from a transcript | recovered text goes in on its own, marked; a person can mark a stretch as a genuine pause or remove recovered text
- The product decides who is speaking | speakers are separated for every recording on its own; a person can name, merge and set speakers
- Chinese is written in Traditional characters as Taiwan writes it | the choice can be made per recording
- One file per interview holds the whole transcript | a person can move a transcript to another interview and choose between two flagged transcripts
- There is always a readable Markdown copy of each transcript | an outside-edited copy is set aside before a fresh one is written
- The product breaks each transcript into paragraphs by meaning | a person can join two paragraphs; splits keep the board place
- The product marks which paragraphs are the interviewer's questions | a person can mark or unmark questions by hand
- Off-topic chatter is set apart | a person can mark or unmark chatter by hand
- The interviewee's words are never altered | a person can correct an original word, keeping its time and links; a site list of names and terms flags likely mishearings, from CFI-077
- Every paragraph not in English gets English | a person can write or correct English and ask for it again
- A person's edits are never lost to an automatic redo | every earlier version is kept and can be brought back
- English and original are linked phrase by phrase on their own | a person can set the original words of an English phrase by hand
- Word-link quality is measured before another way of linking is used | written from the ruling CFI-088
- Every decision is shown and can be set by hand | every decision shown with how it was reached; a value can be handed back to the product; changing one redoes only what depends on it
- What a person sees while footage is processed | the episode's footage list with per-interview progress and problems
- Footage-in works whichever computers the studio has | works on Windows and macOS, behind sign-in
- The studio's existing transcripts are brought in once with every paragraph's address | a content match is offered for a person to accept instead of being taken on its own
- Every existing paragraph is placed in its recording | a person can place a paragraph by hand; the likeness is a site setting
- Montage material is downloaded clips with a credit record | a person can give a clip's credit by hand; montage material refuses interview footage, from CFI-110

## Parts of items left out

- 39-073 | only the editing program's bin is read, never the bins inside it: an arrangement of the editing program
- 39-075 | the refusal naming a command option, and a preview building session 1: a hand-run step that no longer exists
- 39-079 | the refusal of a raw file with no proxy, and messages naming command options: replaced by waiting for the proxy
- 39-081 | messages naming command options, and the "rebased" message: insides
- 39-082 | one timeline per camera in the editing program, its "Angles" bin and naming, the dry run and apply, refusals of existing names, half-built timelines: an arrangement of building in the editing program
- 39-083 | the read-back's item counts and messages: kept as a requirement on the hand-over, messages left to that piece
- 39-085 | driving the editing program's multicam dialog, Windows only, and its messages: belongs to the hand-over (see the join)
- 39-086 | per-camera and combined timelines, the corrected copy and their messages: the older way, folded into one
- 39-087 | track names, colour kept, and the delete or append failure messages of the editing program: arrangement
- 39-088 | finding the interviewee by matching a timeline name to folders, one episode's media folder as its default, and its messages: arrangement
- 41-003 | folders named "archive", "script docs" or "_archive" never treated as people: a folder shape cut by the owner
- 41-004 | the start of a timeline made from the clip, and the project's timeline start setting: sources inside the editing program
- 41-005 | the project's timeline rate: a source inside the editing program
- 41-006 | the recording rewritten in place and the stereo original moved to a "legacy" folder: replaced by never altering the original
- 41-024 | clips nested inside an angle opened up to 8 deep: the editing program's multicam structure
- 40-034 | the retired page, sending clips in order with the first refusal stopping the rest, "no sharing set up on this server", the studio's computers not taking the job: arrangement
- 39-017 | the editing program reachable, clips found by a bracketed id among the episode's video files, "the agent already has a request in flight", and being told to start transcription by hand: arrangement
- 30-034 | "too much work is queued already; try again in a moment" (a limit of the build's own pipe), and line-ups made by another server: arrangement
- 40-010 | the editing program's project store message and its once-a-minute retry: replaced by the product's own transcription
- 40-011 | looking first among montage transcripts by media name, guessing the interviewee from the clip name, and using subtitles to place paragraphs faster: replaced by CFI-109's pointer or exact name
- 40-040 | what the assistant is given per clip, and finding a clip's folder by name, letter case or id tag: assistant tooling and folder shape
- 41-033 | one backup kept once: replaced by every earlier version kept
- 41-040 | the page reachable only from one computer without sign-in: arrangement
- 42-026 | tied to the editing program's transcription: generalised to every transcript
- 43-040 | the clip whose name matches by half its words, and a guessed clip withdrawn: removed by CFI-109
- 43-041 | working a cut out from subtitle exports alone without the editing program: arrangement
- 41-032 | an outside account not having accepted terms: generalised to a reason that trying again will not help
- 41-021 | montage English by a separate translator: open in Q3
- CFI-102 | command-line length on Windows: arrangement; the promise (any number of long-named files, partial results survive a crash) is met

- 41-006 | the silence floor as a site setting: a setting only the build would tune (the -30 dBFS figure stays in the text)
- 41-014 | the gap that counts as missing speech as a site setting and per interview: a setting only the build would tune (the figures stay in the text)
- 43-042 | the 80% likeness as a setting: a setting only the build would tune (the figure stays in the text)

- 30-034 | the daily allowance counted in assistant calls (300, from 0 to 100,000) and its message: replaced by the site's one daily budget in money (the owner's answer of 2026-11-24 to another piece)

## Joins with other capabilities

- cards-board / What the assistant may do | Clips dropped in become an interview ready to cut | the first themes and the first sort of every paragraph are the last automatic step
- cards-board / Cards on the board | Each interviewee is given a colour | the interviewee's colour on their cards, and the clip colours in the order they are given ("Every interviewee has one colour everywhere")
- cards-board / The owner's editorial rules | Off-topic chatter is set apart ; The product marks which paragraphs are the interviewer's questions | chatter left out of the themes; a question set aside in its answer's theme's set-aside group ("Interviewer questions never play")
- cards-editor / The English a cut shows | Footage-in works most urgent first, within the site's daily budget | the settings row's wording when lining up cannot run ("A settings row shows how far the English is lined up with the original")
- cards-to-resolve-and-exports / Placing, deleting and linking clips in Resolve | The interview's multicam is ready for the editing program without one being open | builds the multicam in Resolve with one angle per device, reads it back within a frame; must carry item 39-085's dialog facts and messages and item 39-083's read-back messages
- cards-to-resolve-and-exports / Undo, markers, titles, fades and properties | Each interviewee is given a colour | the multicam wears the interviewee's colour in Resolve from the moment it is made
- cards-editor / The English a cut shows | Word links and glosses inside each phrase ; A cut's English is the English of the words it plays | how the gloss and lit English show, and every card's English
- cards-editor / Search and the transcript panel | A misheard Mandarin word can still be found | search finds soundalike spellings
- cards-editor / Shortening, the edit chat and the assistant | The product marks which paragraphs are the interviewer's questions | the assistant never puts a question into a cut
- fleet-jobs / Choosing who runs what | What transcribing needs and what a person sees while it runs ; Clips dropped in become an interview ready to cut | which able, free computer does the heavy work
- proxies-and-file-moves / Raw camera formats and Blackmagic Proxy Generator | Every take is lined up by sound to within a frame | proxies made for raw camera files
- footage-sorter-and-camera-cards / Sorting into shoots, people and cameras | Clips dropped in become an interview ready to cut | footage the Sorter files from cards does not arrive by itself; a person drops it onto the episode from the folders it was filed in
- youtube / File names and what a file carries | Montage material is downloaded clips with a credit record | a download's channel, title, address and date as its credit
- whole-product / The assistant | Footage-in works most urgent first, within the site's daily budget | the site's one daily budget in money, set by an admin, with the expected cost shown before each task
- whole-product / The assistant | Clips dropped in become an interview ready to cut | the site-wide switch and what is left when it is off

## Joins settled

- cards-board F7 | changed: Each interviewee is given a colour | each new interviewee takes the first free clip colour in the order their footage arrives; pointer names the board's "Every interviewee has one colour everywhere"
- cards-board F8 | changed: Each interviewee is given a colour | anyone signed in who can open Timeline Cards may recolour a person, everywhere at once
- cards-board F9 | no change here: the board changes; this piece already gives one colour per person everywhere
- cards-board F10 | changed: The product marks which paragraphs are the interviewer's questions | a question stays above its answer in the transcript, and on the board goes to its answer's theme's set-aside group, pointing to "Interviewer questions never play"
- cards-board F11 | no change here: the board changes, pointing to this piece for what chatter is
- cards-editor-1 F10 | changed: Every word is timed, and a word's time is for finding it, not for cutting on it | the pointer to the editor's lane dropped, CFI-059's sentence kept
- cards-footage-in F1 | changed: The product breaks each transcript into paragraphs by meaning | assistant-off breaks fall at pauses only at sentence ends, answer fragments under two sentences merged into a neighbour
- cards-footage-in F2 | no change here: the board changes its by-hand pointer to filing an interview under a person
- cards-footage-in F3 | no change here: cards-editor-2 changes
- cards-footage-in F4 | changed: Every interview gets a small preview exactly as long as its sound ; A preview that cannot be made never stops anything else | the interview's preview is its small picture; every montage clip with picture gets a small picture, listening copy and waveform when it lands; the no-preview reasons apply to a recording of an interview
- cards-footage-in F5 | no change here: cards-editor-2 points to the carry-over companion
- cards-footage-in F6 | no change here: cards-editor-3 changes
- cards-footage-in F7 | no change here: cards-editor-3 changes
- cards-footage-in F8 | no change here: this piece is the home and its rule already stands; cards-editor-3 points to it
- cards-footage-in F9 | changed: Footage-in works most urgent first, within the site's daily budget | the quoted sentence dropped; points to the editor's settings row for the wording, the episode's footage uses the same words
- cards-footage-in F10 | no change here: the hand-over changes
- cards-footage-in F11 | no change here: the hand-over takes its rate from this piece's setting
- cards-footage-in F12 | no change here: fleet-jobs drops its option; every transcription separates speakers
- cards-footage-in F13 | changed: Every interview gets a small preview exactly as long as its sound | the interview's preview is at most 480 lines tall and never enlarged; a clip's small picture is picture only, at most 480 lines, never enlarged
- cards-footage-in F14 | changed: Every take is lined up by sound to within a frame | the device search also tries whole-hour shifts and notes the one used
- cards-footage-in F15 | no change here: the Footage Sorter changes to this piece's rule
- cards-footage-in F16 | changed: The interview starts at the crew's first question | one list of self-introduction phrases, the union of both, held here
- cards-to-resolve-and-exports F11 | no change here: the hand-over changes
- cards-to-resolve-and-exports F12 | no change here: the hand-over changes
- fleet-jobs F8 | no change here: fleet-jobs changes; this piece already says it
- fleet-jobs F9 | no change here: this piece is the home and already promises progress at least every 3 seconds; fleet-jobs points to it
- fleet-jobs F10 | no change here: fleet-jobs adds the kinds
- proxies-and-file-moves F2 | changed: Every take is lined up by sound to within a frame | when no raw proxy can be made, the page names the camera, says its clips are in a raw camera format CC Sync cannot make proxies from, and carries on if a proxy appears
- whole-product F5 | no change here: whole-product changes; this piece already has work running on its own wait for the next day's budget
- page 32, 32.4 | changed: Clips dropped in become an interview ready to cut | the claim that card footage reaches the episode on its own removed, and the "Footage Sorter off" line with it; dropping clips is the only way in, from wherever they are, the Sorter's folders included; the join line above corrected
- whole-product F6 | changed: Footage-in works most urgent first, within the site's daily budget | the unavailable message kept only for an assistant that is on; with it switched off nothing about it is shown
