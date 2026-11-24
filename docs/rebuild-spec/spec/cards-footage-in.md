# Timeline Cards: footage in, ready to cut

This is the first step of Timeline Cards: a person drops an interview's clips in and does nothing more. The product works out which clips are one interview, which camera or recorder is which angle, lines the angles up by their sound, makes the multicam, transcribes the speech in the language spoken, breaks it into paragraphs, marks the interviewer's questions, gives every paragraph English, times every word and links the English to the original words, makes a small preview, and finally makes the first sort for the board. No step waits for a person to start it, and no editing program, notes program or folder kept in a certain shape is needed. Every decision the product makes on the way can be seen and set by hand, and a value set by hand is never overwritten by a later automatic pass. Timeline Cards is one part a site can switch on and off, and it is off on a new site: with it off, nobody but an admin sees it (in settings, with its switch), dropped footage is not processed, and nothing already made is deleted.

## Cameras, sound recorders and their clocks

### Recordings are sorted into cameras and recorders by their names

Every recording of an interview belongs to one device, and each device's recordings become one angle. The product decides the device from the file name, by these facts about the studio's recorders and cameras:

| A file name like | Is |
|---|---|
| ending `_Wireless PRO` | the wireless lavalier recorder (a "lav") |
| six digits, an underscore, three digits | the Zoom field recorder (a "zoom") |
| eight digits, an underscore, `ff` | a third kind of sound recorder |
| text, then an underscore or hyphen, then more (`fx3_20260521_9490`, `A001_06271102_C250`) | the camera named by the text before the first underscore or hyphen (`fx3`, `A001`) |
| anything else (`party04120164`) | the camera named by the name with its trailing number removed (`party`) |

This must hold for Blackmagic, Sony and every other naming scheme found on real cards: a camera that numbers every clip differently is still one camera, never one camera per clip.

- On its own: which device each recording belongs to, and whether that device is a camera or a sound recorder, from the file name by the table above.
- By hand: on the interview's page every recording is listed under its device. A person can move a recording to another device, join two devices into one, split a device in two, and rename a device. The hand-set device of a recording is kept through every later pass.

### Each device's clock is chosen on its own and shown

Camera and recorder clocks are wrong by minutes, sometimes by years, so nothing is ever placed by a clock or a file date alone: the clock only gives a starting place, and the sound decides (see "Every take is lined up by sound to within a frame").

For each device the product decides whether its timecode or its file dates tell the time of day:

- Timecode is taken as the time of day when every clip of the device has a start timecode and a creation date, none reads 00:00:00, and every clip's timecode is within 60 seconds of its creation date (a take crossing midnight is corrected by a day).
- Otherwise each file is placed by its creation date, which is only good to one second.
- A Blackmagic RAW file's creation date is the moment it was copied, not shot, so a Blackmagic RAW clip is placed by its timecode or its sound, never by its creation date.
- A record-run camera placed by timecode has its takes joined end to end from the first take's date.
- Every device is placed against one shared zero, so real pauses between takes stay as gaps.
- A device whose clips are dated on another day than most of the video (a wrong clock) is moved so its first clip starts at the reference device's first take, and left for the sound to line up. The interview's page says so.

The clock chosen for each device is shown beside it.

- On its own: each device's clock (timecode or file dates), from the rules above.
- By hand: a person can set a device's clock to timecode or to file dates, or give its offset in seconds, in which case it is shown as "forced" and not measured. A hand-set clock or offset is kept through every later pass.

### One-sided stereo sound is made to play in both ears

An interview recording whose sound sits in only one side of a stereo file plays in one ear in headphones; the Zoom field recorder puts one microphone on one side of a stereo file. Before anything uses an interview's sound, the product measures each channel's loudest point over the whole file. When exactly one channel rises above a silence floor of 30 dB below full scale (a channel peaking under -30 dBFS counts as dead), the interview's sound is made as true one-channel sound from that channel.

It leaves the sound as it is, saying why, when the recording already has one channel, has no sound, has sound in more than one channel (with each channel's level shown), is silent in every channel, or cannot be measured. The same sound on both channels is never changed, and a real second microphone is always kept.

The original recording is never altered: the one-channel sound is a file the product makes from it. That file keeps the original's sample depth (24-bit when the original is not plain samples), may be larger than 4 GB, keeps the original's embedded details, and is checked to be one channel and the same length as the original to the millisecond before anything uses it. A recorder file in floating-point samples can peak above full scale: it is lowered so its peak lands at or below -1 dBFS before it is written in fixed-point samples, so no sample clips.

- On its own: whether a recording is made one-channel, and from which channel, from each channel's loudest point against the silence floor.
- By hand: a person can force the change for a recorder known to write one side only, which takes whichever channel is louder on average, or leave a recording as it is. Either choice is kept through every later pass.

#### Lessons

- Met: CFI-001, CFI-002, CFI-003, CFI-004, CFI-005, CFI-006, CFI-007, CFI-008, CFI-009, CFI-010, CFI-011, CFI-012.

## Frame rates

### Each interview's frame rate and drop-frame are chosen on its own

Every clip's frame rate is handled exactly, and a rate a file states is always kept. The interview's multicam takes the rate shot by the most cameras of the interview (a tie goes to the lower rate). Drop-frame is on when any kept clip at that rate has drop-frame timecode, and drop-frame timecode is always read as drop-frame. Where nothing states a rate, 29.97 drop-frame is assumed; this is also how timecode typed with frames is read when nothing else gives a rate. A montage clip takes the rate its file states, otherwise the same default.

- On its own: the interview's frame rate, from the rate most of its cameras shot.
- By hand: a person can name the interview's rate on the interview's page. It is kept through every later pass.
- On its own: whether the interview's timecode is drop-frame, from the kept clips at that rate.
- By hand: a person can force drop-frame on or off. It is kept through every later pass.
- Setting: Frame rate when nothing states one. Does: the rate given to a clip or interview whose files state none. Default: 29.97 drop-frame. Who: an admin. Applies to: the site. Search words: frame rate, fps, drop frame, 29.97, default rate.

### Mixed rates and off-speed clips are reported as soon as they arrive

Cameras of one interview may shoot different rates: Blackmagic cameras record true 30.000 or 24.000 frames a second, Sony records 29.97 or 23.976. Mixed rates are allowed. The interview's page notes them as soon as the clips arrive, naming each rate, and states the drift they cost within a take, in percent and in frames a minute. The angles stay in sync without drift, and a one-frame mismatch that comes from a true-rate file is not called a fault.

A clip whose sensor rate differs from its file rate plays at another speed than it was shot. Such a clip is flagged on arrival with its speed correction (for example about 96.7%), and it is never lined up by its own sound.

### A clip whose timing or rate is missing or guessed is named before a cut is made from it

Any clip whose word timing or frame rate is missing, or was assumed rather than read, is named on the interview's page with a warning, and the warning is shown again before a cut list is made from it, so a cut is never silently made on coarse timing or a guessed rate.

#### Lessons

- Met: CFI-013, CFI-014, CFI-015, CFI-016, CFI-017.

## Facts about Resolve: rates, multicams, timecode

### Word times count from the interview's own starting timecode

Word times, subtitle times and the transcript all carry the interview's own timecode, so a word's time matches what an editing program shows for the same multicam. The start is taken, in this order: a start a person gives; the interview's own start timecode, as its recordings state it; otherwise 01:00:00:00. A sound recording with no timecode of its own starts at zero. Each recording's word times are measured from that recording's own start, and two timings of one recording are combined only after checking they share a time base.

- On its own: the timecode every word time is counted from, by the order above.
- By hand: a person can give the interview's start timecode on the interview's page. It is kept through every later pass, and every word time follows it.

### The interview's multicam is ready for the editing program without one being open

Everything up to the finished cut works with no editing program at all. When an interview is handed over (see Timeline Cards: the hand-over to Resolve, and exports: Placing, deleting and linking clips in Resolve), these facts about DaVinci Resolve hold, and the interview made here already meets them:

- Resolve's multicam builder sees every file as a separate angle, so a camera that splits one recording into many files would become dozens of angles. The interview's multicam has exactly one angle per camera or recorder, each holding that device's files whole at their places in time with any gaps kept.
- Resolve's scripting cannot create a multicam clip, cannot reach a multicam's angles and cannot set a transcription language. Nothing in getting footage ready depends on any of these, and any step left to a person inside Resolve is named exactly.
- A Resolve clip keeps the frame rate the project had when it was imported, so every position given to Resolve is worked out in that clip's own rate, and what Resolve built is read back and fails loudly when any item is more than one frame from where it was meant to be.
- A Resolve multicam has no media file and no frame rate of its own: its rate and timecode come from Resolve's own record of it.
- An in or out mark left on a clip silently shortens anything rendered from it, so anything rendered from a multicam covers its full length, with any marks cleared first.

#### Lessons

- Met: CFI-018, CFI-020, CFI-021, CFI-022, CFI-023, CFI-024, CFI-025, CFI-026.

## Grouping clips and building the multicam

### The product decides which clips are interview takes and says why each other clip was left out

Of the clips dropped in for an interview, the product keeps the interview takes and leaves the rest out, each with its reason shown on the interview's page:

| Left out | Reason shown |
|---|---|
| a clip a person excluded | excluded by hand |
| anything that is not sound or picture | not media, with its kind |
| a clip with no start timecode, length or rate that can be read | the missing fact named |
| a clip with no readable creation date and no timecode to place it by | the missing fact named |
| a clip under 3 seconds, unless a person included it | "N s, under the 3 s floor" |
| a video clip under 5 minutes that no other camera's long take overlaps in time | "<len> stray: no interview take of another camera overlaps it" |
| sound outside the span of the kept video, unless it is dated on another day than most of the video (a wrong clock), which keeps it | "<len> of audio outside the interview" |

When nothing is left the page says that nothing dropped looks like an interview take. Nothing left out is deleted or moved.

- On its own: which clips are interview takes, from the rules above.
- By hand: a person can exclude or include any clip, keep only some devices, and change the minimum clip length (3 s) and the stray-video length (5 minutes) for the interview. A clip included or excluded by hand stays so through every later pass.

### A day with several interviews is split into sessions

With the kept video in time order, a gap of more than 30 minutes after everything so far starts a new session. Each session is processed as an interview of its own, and its names carry the session number when there are several.

- On its own: where one session ends and the next begins, from gaps of more than 30 minutes.
- By hand: a person can join sessions into one interview, split a session at a time they choose, lay a whole drop out as one session, or change the session gap. A hand-set split or join is kept through every later pass.

### The product decides which person each recording belongs to

Every interview is filed under one interviewee of the episode. The product compares the recording's name (with a trailing "Multicam" removed) with the people already in the episode, in this order:

1. a pairing of that recording to a person, given by hand, always wins;
2. a person whose name is the same, ignoring letter case, is a sure match;
3. the closest name, when at least half of the recording name's parts match a person's name parts (a part found inside another part counts as a partial match), is a likely match. This catches a first name given alone, and given and family names in the other order or spelt with a hyphen differently;
4. otherwise a new person is made, named after the recording.

A likely match is shown as a question ("Is this <person>?") for a person to confirm before the interview is filed under that person; the work that does not depend on who it is (lining up, transcribing, translating) carries on meanwhile. A sound file whose name matches no known interview is never filed by a guess from its name: it is reported, and matched by what is said in it (see "The interview's sound is always the recorder's").

The interview's page also shows who introduces themselves and when (see "The interview starts at the crew's first question"), because a drop can hold someone else's interview and one recording can hold two interviews.

- On its own: which person an interview belongs to, from its name by the order above.
- By hand: a person can file an interview under another person, confirm or refuse a likely match, move one recording to another interviewee, and split one recording into two interviews at a time they choose. A hand-set filing is kept through every later pass.

### The interview's names are chosen on its own

The interview is named after the person it is filed under, with the session number when there are several; its multicam and its transcript carry the interview's name.

- On its own: the names of the interview, its multicam and its transcript, from the person and the session.
- By hand: a person can rename the interview, the multicam and the transcript, each on its own. A name set by hand is kept through every later pass, and renaming never loosens a cut, a paragraph address or a translation.

### The product chooses the device every other device is lined up against

The reference is the Zoom recorder, else the lavalier, else the camera with the most frames. A source that is silent or nearly silent for the whole interview (a dead lav or camera track) is never the reference or the interview's sound: the next in that order is chosen, and the interview's page shows the choice and why.

- On its own: the reference device, by the order above.
- By hand: a person can name another device as the reference. Naming a device the interview does not have is refused with "no device '<x>' (have: ...)". The hand-set reference is kept through every later pass.

### The interview's sound is always the recorder's

The Zoom recorder is the interview's own microphone, so the sound under every angle of the multicam is the Zoom recording, and switching angle never changes the sound. The Zoom files are placed by their measured offset, longest first; a later part of a recording the recorder split is expected where the previous part ended, and its measured place is used only when it is within 20 seconds of that.

The recorder's sound is matched against every camera file of the interview, so a recorder covering only part of the interview (only its second hour, say) is still placed. Where the recorder stops early, the interview carries the best camera sound for the rest rather than going silent, and the interview's page says from where.

When no recorder sound is found for an interview, the multicam and the interview's sound are not made. First, every loose recording over 7 minutes in the episode is matched to the interview by what is said in it, and any match is reported, because an interview "with no recorder" usually has its recorder file filed elsewhere. The interview's page then says that no Zoom recording was found, names the sound devices it does have, and says where to look. Work that does not need the interview's sound carries on.

- On its own: which device's sound is the interview's sound: the Zoom recorder, filled from the best camera sound where it stops.
- By hand: a person can add the missing recorder file, accept a reported match, or name another device whose sound is to be the interview's sound. The choice is recorded on the interview and shown with it, and it is kept through every later pass.

### Every take is lined up by sound to within a frame

Before anything is made, each device's sound is compared with the reference device's:

- First a constant offset for the whole device is searched for, far enough to find a source an hour either side of where its clock places it.
- Then each take is matched within 4 seconds of where that offset places it.
- A match is trusted only when it is strong and clearly better than any other match more than half a second away.
- Takes under 3 seconds, silent, with no sound, or with no reference sound under them are not measured.
- The middle value of the trusted matches is the device's offset. A trusted match more than 1.5 seconds from it is an outlier. Every take without a trusted match is moved by the device's offset, never left at its clock time.

Every take of every angle ends up within a frame of its sound. The interview's page lists every take with its device, file, clock, position, correction, strength and verdict. If no device matches the reference at all, the page warns plainly that nothing in the interview matched the reference, names it, and suggests checking it and naming another reference and another sound device.

A camera with no usable sound can be placed only by its clock: such an angle is marked unverified, for a person to check. The cameras found are shown per session, and the multicam never opens on an empty stretch.

A raw camera file is heard and seen through its proxy. A raw file with no proxy yet waits for one to be made (see Proxies and file moves: Raw camera formats and Blackmagic Proxy Generator), and the interview's page names the camera it is waiting for.

- On its own: each device's offset and each take's place, from its sound against the reference.
- By hand: a person can give a device's offset in seconds instead of measuring it, move one take by hand, accept an unverified angle as checked, or have a device placed by its clock alone, skipping the sound. Each is kept through every later pass.

### Every camera piece is checked against the sound along its whole length

A piece of picture that is in sync at one instant can drift from its sound over its length. After placing, each camera piece's own sound is matched against the interview's sound at 6 points along it: up to 15 seconds of the interview's sound, searched for within 25 seconds either side of where the piece is said to sit. A point counts when the match is clearly strong. At least 3 points, and at least half of those tried, must agree within two frames; the agreed offset then moves the picture. A piece too short to test (under 4 seconds) takes the offset of another piece from the same file.

A piece whose points spread by more than a frame is shown with "DRIFT over a frame: a slip cannot fix it". A piece that fails the check is left out of the preview, whatever it covered shows through, and the check runs again, up to 4 times, with the reason shown (how many points matched, or that the file is too short for the piece). If nothing usable remains, no preview is made and the person is told why.

- On its own: whether each piece's picture sits on its sound, and by how much it is moved.
- By hand: a person can keep a failed piece where it was said to sit, marked unverified, or move it by a number of frames. Either is kept through every later pass.

### A person can line an interview's picture up again

On the interview's page a person can ask for the picture of every angle (or of the angles they pick) to be measured against the interview's sound again and moved onto it, by the check above. Each piece is reported as "in sync" or "SLIP +N frames", or as unsure ("UNSURE: N of N probes matched", or that the probes disagree), and an unsure piece is left alone. Only picture moves: every piece of sound keeps its exact position and in-point, checked before and after, and if the sound changed at all nothing is kept and the person is told. If the picture would start before its file, the piece starts later instead. A person can see what would move before anything does.

- Who: anyone signed in who can open Timeline Cards.

### A person can swap in a better recording of the interview's sound

A cleaner recording of the same interview (a second recording of an online interview, a recorder file found later) can replace the interview's sound. Two recordings of one interview can drift up to 0.6 seconds apart, so the new recording is aligned piece by piece, keeping every word and every cut within 5 ms over almost the whole interview. The interview's length stays the same to the frame, every cut span stays intact, the word timing is reused, the new sound is levelled, and the angles that were correct are left untouched. Where the new recording cannot cover every span the cuts use, the tail is filled from the earlier sound, or, if that cannot be done, the swap is refused and the person is told; a cut is never left over silence. A person can see what would change before anything does.

- Who: anyone signed in who can open Timeline Cards.
- On its own: the level of the new sound, by EBU R128 loudness normalisation to -23 LUFS.
- By hand: a person can switch the levelling off, or level alone without swapping, on the interview's page.

### The product decides the order of the angles

Blackmagic-style cameras (names like A001) come first, then `fx3` cameras, then the rest by name.

- On its own: the order of the angles, by the rule above.
- By hand: a person can set the order of the angles. A name that is not one of the interview's cameras is refused with "no video device named ... (have: ...)". The hand-set order is kept through every later pass.

### Long empty stretches can be shrunk and a single camera laid back to back

The multicam keeps real pauses as gaps. On a person's request:

- every stretch longer than a length they give that no device covers is shrunk to 2 seconds, and the page says how many stretches and how much time was taken out;
- every clip is trimmed to a start and end time they give, and clips wholly outside are left out (with nothing left, the request is refused and the person told that the times leave nothing);
- a single camera that stopped between takes is laid out with its takes back to back in recorded order, so a stop-start event is not mostly empty.

Everything is always shifted together so nothing sits before the first frame.

- On its own: nothing is shrunk, trimmed or laid back to back.
- By hand: a person sets each of the three on the interview's page, and each is kept through every later pass.

### What the interview's multicam holds

Each interviewee gets one multicam per interview. It holds only interview takes (b-roll is left out), one angle per camera or recorder, each angle with that device's picture alone, every take in its place in time with gaps kept, all at the interview's frame rate and drop-frame, and the interview's sound under every angle. It starts at the crew's first question and ends at the earlier of the end of the last interview take and the end of its sound. A multicam of one angle is allowed.

The interview's page shows the whole plan: the devices, the reference, the sound source, each device's clock, the sessions, every take (device, file, clock, position, correction, strength, verdict), what was left out and why, and each angle with its number of clips and length. Nothing a person dropped in is deleted or moved.

### The interview starts at the crew's first question

The real start of an interview is where the crew asks the person to introduce themselves, and the multicam begins there. The product listens to the opening 15 minutes and looks, earliest first within each search:

1. for a question: 自我介紹, 介紹一下, 介紹自己, 介紹您自己, 介紹你自己, 先介紹, 簡單介紹, 請介紹 (in either Chinese script), or, ignoring case, "introduce yourself", "introduce yourselves", "tell us who you are", "tell me who you are", "who you are and what you do", "your name and", "start by introducing";
2. for a bare 介紹;
3. for the answer, only in the first 10 minutes: a line that begins 我是, 我叫 or 大家好 after any filler, or "my name is", or "I'm" or "I am" followed within 100 characters by "and I".

The start is 0.75 seconds before the question (1.5 seconds before an answer), never before the window, so the opening question is included even when it is too faint to hear well. The interview's page shows the time chosen, how it was found, and the line with two lines either side; or "not found" with the lines heard and advice to widen or move the window.

- On its own: where the interview begins, from the introduction found.
- By hand: a person can move the start to any moment, or move or widen the window searched, without anything being rebuilt. The hand-set start is kept through every later pass.

### Which picture the preview shows

The interview's preview shows the multicam's first angle. If that angle has no picture, the next angle with picture is used, and the person is told. Every camera piece is shown at its own time; where pieces overlap, the later one wins and the person is told how much of the earlier still shows. A piece whose camera file is missing shows black and is noted. Still images are skipped with a note. A piece that may have a speed change is noted and kept only if its sound check passes. The person is told how many seconds of the whole are black. When no angle has any picture, the preview is sound alone and says plainly that there is no picture.

- On its own: which angle the preview shows, from the first angle with picture.
- By hand: a person can choose the angle the preview shows on the interview's page. It is kept through every later pass.

### Each interviewee is given a colour

Each interviewee gets one colour, assigned when their first footage comes in and used for their cards on the board and for their multicam wherever it is shown, including in the editing program from the moment it is made there (see Timeline Cards: the board: Cards on the board, and Timeline Cards: the hand-over to Resolve, and exports: Undo, markers, titles, fades and properties). Until then a person sees "no colour assigned yet".

- On its own: each interviewee's colour, when their footage first comes in.
- By hand: a person can pick another colour for an interviewee. It is kept through every later pass.

#### Lessons

- Met: CFI-027, CFI-028, CFI-029, CFI-030, CFI-031, CFI-032, CFI-033, CFI-034, CFI-035, CFI-036, CFI-037, CFI-038.

## Facts about Resolve's own transcription

### A transcription made in the editing program is never the transcript

Every transcript the editor relies on comes from the product's own speech-to-text (see "Transcripts come only from the product's own speech-to-text"). The product never runs, offers or reconciles a transcription made inside DaVinci Resolve, because of these facts about it: it silently drops stretches of speech (a cut-off end, or a passage in the middle) with no error and no visible seam; it stops early on 32-bit floating-point recordings that peak far above full scale; running it again without clearing it returns the same cut-short result; it can only be started by a person inside Resolve; it writes Mandarin in Simplified characters and ignores sentence ends; it sometimes crushes a sentence into one millisecond; it writes "(Speaking In Foreign Language)" where it heard the wrong language; its transcript holds its own "(...)" pause markers and paragraph breaks; and its subtitle exports carry the project's start timecode, normally 01:00:00:00.

A Resolve transcription or subtitle export the studio already holds is used only when its existing transcripts are brought in, and only to help place their paragraphs (see "Bringing the studio's existing transcripts in once"). Anything brought in that way is compared in its own time base (normally starting at 01:00:00:00), checked for holes against the product's own transcription of the same recording, and swept for tiny cues that carry real text, starts that run backwards and absurd speaking rates; those spots are flagged before a cut uses them. A stretch filled with "(Speaking In Foreign Language)" or one token repeated is treated as the wrong language, and no cut is placed in it. Mandarin from it is compared in either script or a mix, and no card's text or boundaries depend on it.

#### Lessons

- Met: CFI-040, CFI-043, CFI-044, CFI-045, CFI-046, CFI-048.

## Speech-to-text: rulings

### Transcripts come only from the product's own speech-to-text

The text of every recording and the time of each of its words come from one hearing by the product's own speech-to-text, so they always agree. Transcription, and every fact about a clip it needs, works with no editing program open and never connects to one. When a speech-to-text service the site pays for refuses for lack of credit, transcription carries on with the studio's own, and each transcript names what made it. Every interview has word timing; interviews brought in without it get it on their own, and a recording that has none says why.

### The language of every stretch of speech is decided on its own

Interviews often mix languages. Unless a person fixes one language for a recording, the product decides per stretch, never per file and never from a person's name:

- speech is cut into pieces at pauses of half a second or more, each at most 20 seconds long;
- each piece of at least 1 second has its language judged; a judgement under 60% sure decides nothing, and an undecided piece takes the language of the piece before it (at the start, of the first decided one);
- neighbouring pieces in one language form a run;
- a run with less than 3 seconds of speech whose language differs from all its neighbours (a crew aside, a stray word or two) is taken into the run before it, or the run after it at the very start;
- each run is then transcribed in its own language, the line at each switch is kept, and the transcript stays in time order.

When this cannot be done, the language is judged per 30 seconds instead, and failing that once for the whole recording, and the person is told which happened. Each recording shows how its language was decided (per stretch, per 30 seconds, or fixed by a person) and the minutes in each language, for example "en (en 27.1 min, zh 1.4 min, 3 runs)".

No language is ever forced across a batch of recordings. When a person fixes a language, the result's own confidence is not trusted: the transcript's language is checked once it is made, and a recording that does not sound like the language fixed is flagged before anything is built from it.

- On its own: the language of each stretch of speech, by the rules above.
- By hand: a person can fix one language for a whole recording, or set the language of one stretch, and have it transcribed again. A language set by hand is kept through every later pass, and each transcript shows which language it was made in.

### Each recording's main language is decided on its own

A recording's main language is the one with the most seconds of speech; a tie goes to the language heard first. A recording is marked mixed-language when more than one language was heard.

- On its own: the main language, from the seconds of speech in each.
- By hand: a person can set the main language on the interview's page. It is kept through every later pass.

### Each speaker is transcribed in their own language, and an interpreter can be left out

Each speaker's speech is transcribed in the language they speak. Where an interviewer or an interpreter repeats the interviewee's words in another language, the interviewee's own words are kept and the interpreter's lines can be dropped from the paragraphs.

- On its own: nothing is dropped.
- By hand: a person marks a speaker as the interpreter on the interview's page, and that speaker's lines are left out of the paragraphs and the board. Unmarking brings them back. The mark is kept through every later pass.

### Nothing said is missing from a transcript

A transcript covers the whole recording, including its end and the interviewer's quiet questions. Every transcript is checked throughout, not only at its end:

- a gap between transcribed words counts when it is at least ten times that interview's own usual gap between lines and never under 6 seconds;
- a thinned stretch (few words a minute) counts too;
- a gap or thinned stretch is dropped speech when voice is heard in it for at least 2 seconds; otherwise it is a genuine pause;
- a transcript ending more than 10 seconds before the recording ends is cut short (this end check is labelled a tail check, and is never the whole health check); a sound file more than 1 second shorter than its clip is short;
- where a transcript is compared with another text of the same recording, what is measured is missing text (whether the other text's words appear anywhere within about 90 seconds), never seconds of overlap.

Any stretch over 3 seconds where speech is audible but no words came back is transcribed again on its own, and its text goes into the transcript in its place, marked as recovered. The interview's page lists every dropped stretch with its times and the total, a chart of how much of each minute is covered, and every run of minutes under 35% covered; with no dropped stretch it says so plainly. A stretch that still has no words after this is shown as a hole, and the person is told to look at it before anything else, because it would be a hole on the board.

- On its own: whether a stretch of the transcript is missing, from the gaps against that interview's usual gap, the words a minute, the end against the recording's length and whether voice is heard; and the text put into it, from transcribing that stretch again.
- By hand: a person can mark a flagged stretch as a genuine pause, and remove or correct recovered text. Each is kept through every later pass.

#### Lessons

- Met: CFI-049, CFI-050, CFI-051, CFI-052, CFI-053, CFI-054, CFI-055, CFI-056, CFI-057, CFI-058.

## Speech-to-text: facts and situations

### What transcribing needs and what a person sees while it runs

Transcribing a recording needs a computer of the studio's that can reach the recording and has a graphics card with at least 6 GB of memory; which computer does it is decided as in Work shared out across the computers: Choosing who runs what. Transcription waits for a computer with a usable graphics card. Only when no computer of the studio's has one, or when a person picks a computer without one, does it run on that computer's processor, and the person is told the reason and that it will be much slower.

While a recording is transcribed the person sees, at least every 3 seconds: which recording of how many, the percentage, minutes done of the total, lines so far, the language and the time left. At the end of a batch the person sees how many were done, failed and skipped, minutes of sound against minutes taken, and each failure with its reason. One failed recording never stops the others. After a batch every recording is checked for a transcript, and each one missing is tried again or listed with its reason; none is silently skipped.


### A person can transcribe clips from the editor

A clip with no transcript is marked as untranscribed wherever it shows in the editor. A person can have one clip, every untranscribed clip, or the untranscribed clips of the open cut transcribed, on a computer they pick from a list of the studio's able computers, which starts on the computer picked last time. The page answers at once with how many clips and folders were found, then shows progress as "[n/N] name" (the name cut to 80 characters) and the end result. When the computer picked is not available, the work goes to another able computer instead.

The messages a person can meet:

- "[speech-to-text] queued on <machine>: N clip(s)"
- "[speech-to-text] started: N of M clip(s) found, N folder(s)"
- "a [speech-to-text] run is already going -- one at a time"
- "transcribe: no clip ids"
- "none of those [id]s are under <media>"
- "that clip belongs to <episode>, not this one: switch to that episode to transcribe it"

- Exact: yes
- Ways in: from the editor, on a clip, on the open cut, or for every untranscribed clip of the episode; from the interview's page, to have a recording transcribed again.

### Every word is timed, and a word's time is for finding it, not for cutting on it

Every word carries its start, its end, its text and, when known, who is speaking. Mandarin words arrive from speech-to-text one character at a time, so characters are grouped back into real words before anything works on them; nothing assumes one timed word is one dictionary word. A word's time from speech-to-text does not mark exactly where the word starts in the sound, so it is never used as a frame-accurate cut point: anything that needs one measures the sound itself (see Timeline Cards: the editor: The lane: clicking, trimming, zooming and dragging). A card shows exactly the words audible within its cut, with none that are heard greyed out and none that are not heard shown.

### The product decides who is speaking

Every recording, interview or montage clip, has its speakers separated. Each word is given the speaker it overlaps most; a word overlapping no speaker takes the nearest speaker within half a second, else none. A word gets a speaker only where that voice clearly owns it; a wrong label is worse than none, so a doubtful word stays unlabelled. The person sees the number of speakers and turns per recording. If separating speakers fails for any reason, the transcript is still made without speakers, and the reason is recorded and shown; when the reason means trying again will not help, the person is told so.

- On its own: who is speaking each word, from the voices.
- By hand: a person can name each speaker, merge two speakers, and set the speaker of any line. A speaker set by hand is kept through every later pass.

### A recording already transcribed is not transcribed again

A recording already transcribed is not done again while its sound is unchanged: the same size and modified time (to a hundredth of a second), or failing that the same content at its start and end, which also recognises the same file copied elsewhere. Checking a recording that is already done costs seconds. A recording whose words are missing or empty, or whose sound has changed, is transcribed again on its own.

- On its own: whether a recording needs transcribing again, from its sound.
- By hand: a person can have any recording transcribed again anyway, from the interview's page. A transcription done again never overwrites what a person set by hand (see "A person's edits are never lost to an automatic redo").

#### Lessons

- Met: CFI-059, CFI-060, CFI-061, CFI-062, CFI-063, CFI-064, CFI-065, CFI-066, CFI-067, CFI-068.

## Chinese script

### Chinese is written in Traditional characters as Taiwan writes it

Every stretch judged to be Mandarin, or holding any Chinese character, is written in Traditional Chinese as Taiwan writes it, phrase by phrase with Taiwan phrasing, and then every 臺 becomes the house form 台. Every Mandarin transcript, word, subtitle line and card reads this way, and search treats the forms the same. Text in another language is never converted.

The words of a stretch are converted together as one sentence and then split back onto the words, so each timed word's text matches the sentence text character for character. Timed pieces are joined with a space unless the join falls between Chinese or Japanese characters, so English words never run together. When conversion cannot be done, the text stays as heard and the person is told. Montage clips are converted only when judged to be Mandarin or holding Chinese characters.

- On its own: how Chinese is written: Traditional, Taiwan phrasing, 台.
- By hand: a person can choose no conversion, keeping 臺, or another script for a recording or for the site. The choice is kept through every later pass.
- Setting: Chinese script. Does: how Chinese text in transcripts is written. Default: Traditional Chinese with Taiwan phrasing and 台. Who: an admin. Applies to: the site. Search words: traditional, simplified, Taiwan, Chinese characters, script.

### A misheard Mandarin word can still be found

Mandarin speech-to-text writes soundalike characters, so a transcript keeps what is needed for search to find a Mandarin term by its soundalike spellings; a misheard word never hides the passage (see Timeline Cards: the editor: Search and the transcript panel).

#### Lessons

- Met: CFI-069, CFI-070, CFI-071.

## The transcript and its English

### One file per interview holds the whole transcript

Each interview has exactly one transcript, and it is one file holding everything together: the text in the language spoken, its English, the time of every word, who is speaking, the paragraphs with their addresses and question marks, and which English words go with which original words. These are tied to each other directly and never found again by matching text, so correcting a word can never loosen its timing or its translation. The text, its subtitle lines and the word times come from one hearing, so a paragraph can always be found in the word times. A stretch that came back with no separate words becomes one word covering the whole stretch, so its text is never lost. The text keeps a pause marker "(...)" where speech paused for a while.

Reworking an interview's paragraphs updates its one transcript in place. An interviewee with more than one interview (a second session) has one transcript per interview, and every one of them counts; none is silently ignored. A second transcript of the same interview is flagged for a person, never merged in and never silently replacing the first. An interview whose transcript is finished is not prepared again on its own.

- On its own: which interviewee and interview a transcript belongs to, from the footage it was made from, and whether that interview is already prepared.
- By hand: a person can move a transcript to another interview, and choose which of two flagged transcripts is the interview's. Each choice is kept through every later pass.

### There is always a readable Markdown copy of each transcript

Beside each transcript the product keeps a readable Markdown copy that can be taken elsewhere. Each paragraph in it reads, in order: its question mark when it is an interviewer's question, its English, then the original, then its address; an English interview shows its words once. The product writes the copy and keeps it in step with every change made in Timeline Cards, within a minute. It does not follow changes made to the copy in another program. When the copy has been changed outside the product since it was last written, the changed copy is set aside under a name that says so before a fresh copy is written, and the interview's page tells the person.


### The product breaks each transcript into paragraphs by meaning

A transcript is split into paragraphs by meaning, and each paragraph becomes one card on the board. The rules:

- one interviewer question per paragraph;
- one coherent answer point per paragraph, about 1 to 6 sentences; where the transcription broke a sentence with an ellipsis marker, the pieces are joined back with a space and the marker dropped;
- an answer paragraph holds at least two sentences: a shorter fragment is merged into a neighbour, keeping the first one's address;
- off-topic chatter has paragraphs of its own (see "Off-topic chatter is set apart");
- each paragraph aims at about 20 seconds of speech (about 90 Mandarin characters or 50 English words) and is never more than 60 seconds: a long answer is split even when it is one point, at its own turns (a new example, a move from problem to solution, a "but", a change of subject). A paragraph longer than 60 seconds is never let through.

Length is estimated at 4.5 Chinese characters a second when any line holds 10 or more Chinese characters, otherwise at 2.5 words a second; addresses and source lines do not count. A well-paragraphed interview of about an hour comes to 60 to 200 paragraphs, the middle one about 10 to 30 seconds of tape; far fewer means it was split too coarsely and it is split further. The interview's page shows the number of paragraphs, the typical, ninth-decile and longest lengths, and how many are over the limit, each over-long paragraph with its length and opening words.

Splitting or joining paragraphs that are already on the board never loses their place there: the parts keep the place of the paragraph they came from.

- On its own: where each paragraph begins and ends, from the transcript's text and its timing by the rules above.
- By hand: a person can split a paragraph at a point they choose, join two paragraphs, and allow one paragraph to be longer than the limit. A break set by hand is kept through every later pass.
- Setting: Longest paragraph. Does: the most speech one paragraph, and so one card, may hold before it is split. Default: 60 seconds, aiming at about 20. Who: an admin. Applies to: the site. Search words: paragraph length, card length, split paragraphs, 60 seconds.
- When the assistant is off: paragraphs break at every pause of 1.2 seconds or more, within the same length limits, and a person sets any other break by hand.

### Splitting a paragraph never changes a single character of what was said

A paragraph is split at points named by their exact opening words. For a paragraph holding both the English and the original, the split points are given per language, both must give the same number of parts, and the parts are paired in order. A split is refused, with nothing written, when a split point is not found, is found twice, or is at the very start; when any line or paragraph would lose or gain a character other than spacing; when it would give only one part; or when the languages give different numbers of parts. The person is shown how many paragraphs became how many and which are still too long, and can see the result before anything is written.

### The product marks which paragraphs are the interviewer's questions

Lines where the crew asks a question are marked as interviewer questions, in both languages, decided from what is said (the questions are buried in the run-on speech). A paragraph counts as a question when every line of it is marked. A question is kept directly above the answer it sets up, on the board as in the transcript, and travels with it; the assistant never puts a question into a cut on its own (see Timeline Cards: the editor: Shortening, the edit chat and the assistant).

- On its own: which lines and paragraphs are interviewer questions, from their content.
- By hand: a person can mark or unmark any line or paragraph as a question. The mark is kept through every later pass.
- When the assistant is off: no question is marked on its own; a person marks them.

### Off-topic chatter is set apart

Sound checks, door noise, filming and scheduling logistics, restarts, goodbyes and talk about translating are put in small paragraphs of their own and marked as not content, decided from what is said. They are left out of the themes when the board is first sorted (see Timeline Cards: the board: The owner's editorial rules).

- On its own: which paragraphs are off-topic chatter, from their content.
- By hand: a person can mark or unmark any paragraph as chatter. The mark is kept through every later pass.
- When the assistant is off: nothing is marked on its own; a person marks it.

### The interviewee's words are never altered

Making paragraphs, marking questions and chatter, and adding English never change the words heard, in any language; only line breaks and marks are added. The original text stays character for character what was transcribed, mishearings included (a misheard place or name stays misheard), because every word must still be found at its exact time in the recording; a correction of a mishearing goes only into the English. The same holds for misheard names and terms in an English interview.

Words that look like mishearings of a name or term on the site's list of names and terms are flagged on their paragraph for a person to look at.

- By hand: changing an original word is a step a person chooses: they correct the word on the interview's page, and the word keeps its time and its links to the English.
- Setting: Names and terms. Does: the list of people, places and terms that likely mishearings are checked against. Default: empty. Who: an admin. Applies to: the site. Search words: names, terms, glossary, mishearing, spelling.

### Every paragraph has a permanent address

Each paragraph has a short address of 6 lowercase letters and digits, unique within its transcript; a paragraph that already has one keeps it, through every edit, split, join, re-transcription, respelling and rename. Across a shoot each paragraph is known by its person and its address, so editing one person's transcript never changes another's paragraphs. A new address is never one already used by another transcript of the same person. If two paragraphs brought in from elsewhere share a person and an address, the interview's page names both and asks a person to give one a new address; nothing using either is touched until they do.

### Every paragraph not in English gets English

Any language other than English is recognised and every paragraph in it gets English; real English is never sent for translation. Every interview ends up with a complete original text and a complete English text. The rules for the English:

- fluent English, as for documentary subtitles;
- every name transliterated;
- nothing but the translation, on one line;
- anything the transcription misheard is corrected in the English only.

English that still contains a Chinese character counts as missing: it is asked for again more firmly, and a third time with one worked example; after three refusals the paragraph keeps its original alone and the person is told. A connection failure fails only that paragraph, which is tried again later. A line counts as the Mandarin one when at least a fifth of it is Chinese. The English stands above the original in every bilingual paragraph, and adding English never moves a paragraph address a cut already uses. Each finished English appears as soon as it is made; when translation is slowed or failing, the interview's page says so and why.

English made or corrected on any computer appears on every other, and saving never removes anyone else's English.

- On its own: whether an interview needs English, from the language of its original text, and the English of each paragraph.
- By hand: a person can write or correct the English of any paragraph, or ask for it to be made again. English set by hand is kept through every later pass.
- When the assistant is off: no English is made on its own; each paragraph without English says so, and a person can write it.

### A person's edits are never lost to an automatic redo

Whatever a person has set in a transcript (a corrected word, its English, a paragraph break, a question mark, a speaker) is kept when the recording is transcribed again, paragraphed again or respelt: a later automatic pass fills only what a person has not set. Transcription never writes into the folders holding the footage, and never overwrites a hand-corrected transcript unless a person explicitly asks for it, and then every earlier version is kept and can be brought back.

New word times from a fresh hearing only move where a clip's words start and end; the words stay in the transcript's own wording and characters, so their English stays attached. Re-transcribing, re-paragraphing, respelling or renaming an interview keeps every existing cut's reference and every translation attached, and no translation is paid for again. A change to a transcript shows on every card and saved cut within minutes, with no restart and no edit. A change in how cut spans are worked out moves no placed cut's start or end unless the editor is shown each change and accepts it.

#### Lessons

- Met: CFI-072, CFI-073, CFI-074, CFI-075, CFI-076, CFI-077, CFI-078, CFI-079, CFI-080, CFI-081, CFI-082, CFI-083.

## Word links between the original and the English

### English and original are linked phrase by phrase on their own

For every finished transcript, and for every cut, the product lines the English up with the original: the English is split into short phrases, each tied to the run of original words it translates. It runs by itself once a transcript is finished, does only what is new, and the links are kept in the interview's one transcript file, so nothing is paid for twice.

- The original's words are the timed words where they exist; elsewhere each Han, hiragana or katakana character is a word, and a run of letters, digits and marks is a word (an apostrophe or hyphen inside keeps it whole: "don't", "когда-нибудь").
- The assistant is told the language: Taiwanese Mandarin, Mandarin Chinese, Russian, Ukrainian, Russian or Ukrainian, Japanese, Korean, else "the language it is spoken in".
- An answer is kept only if every phrase names a range of original words inside the original; every phrase is found in the English, in English order and without overlapping another; every English word is inside some phrase ("<word> is not mapped to any original word"); with 4 or more original words, the phrases together reach at least half of them; and there are at most 400 phrases and none empty. The original side may cross, because word order differs between languages; that is never a refusal.
- A line-up belongs to the exact words: editing either the original or the English makes it stale, and a stale one is never used.
- Limits: the original at most 4,000 characters, the English at most 6,000, at most 1,500 words; "nothing to align" when either side is blank.
- A paragraph whose answer failed its checks is tried once more on the next run; one that fails twice is shown with a plain reason, such as "English is a summary, not a translation". A request that got no answer is tried again after an hour, or at once when an editor is waiting on it; a paragraph the assistant left out is asked once more alone. Every request is given room to finish, and an answer already paid for is never thrown away for being slow.
- A cut whose English is the transcript's own (whole or trimmed) is lined up from its paragraphs' line-ups without asking the assistant, when the paragraphs cover nine tenths of the cut and every kept phrase appears word for word, in order, in the cut's English.

- On its own: which English phrase goes with which original words.
- By hand: a person can ask for a paragraph to be lined up again, and can set the original words of any English phrase by hand. A link set by hand is kept through every later pass.
- When the assistant is off: nothing is lined up on its own; a selection of English stands for an approximate span (see "What a selection of English stands for"), and lining up starts again by itself within about a minute of the assistant being switched back on.

### Word links and glosses inside each phrase

Inside each phrase the assistant links each English word to the original word or words it renders, gives every original word a literal gloss of 1 to 3 words, and names runs of original words that form one word, name, compound, abbreviation or fixed expression. Such a run is linked and glossed as a whole, with the gloss on its first word: any of its characters lights all of its English, and no word boundary falls inside it.

- A link is kept only if it stays inside its phrase; a stray link is dropped on its own and the paragraph's other links are kept. At least half the phrases must get a link. A gloss is at most 40 characters on one line. Runs are 2 to 12 words and do not overlap; odd ones are dropped. Word links go stale with their line-up.
- The gloss line shows each original word's gloss in the original's order, "·" for a word with none, words inside a run skipped, two spaces between.
- The English of a spoken word is its word links; with none, its whole phrase, but only when that phrase is 4 English words or fewer. With word links, a spoken word no link names (a filler) lights nothing.
- A cut's word links come from its paragraphs' links when every paragraph it lies in has them, without asking again. Glosses from several paragraphs on one word are joined with " / ".
- A failed answer is tried once more on the next run, and one with no answer is tried again after an hour.

How the gloss and the lit English show in the editor is described in Timeline Cards: the editor: The English a cut shows.

### What a selection of English stands for

When a person selects English in a paragraph or a card, the selection is trimmed to whole words and stands for original words:

- When the paragraph is lined up, the selection touches some English phrases, and the original words are the smallest unbroken run covering every word those phrases translate. Because word order differs between languages the run may include a word no selected phrase names, but it is never scattered and never half a word.
- When there is no checked line-up (the assistant is off or unavailable, the day's budget is spent, an answer failed its checks, or it is not done yet), the selection stands for the whole original sentence or sentences it is in, when the English and the original have the same number of sentences (more than one); otherwise for the whole original paragraph. This is always labelled Approximate, with the reason.
- A selection in a paragraph not yet lined up asks for that paragraph at once, ahead of everything else; a newer selection withdraws the older request. A paragraph whose last request got no answer is asked again once per visit to the page.

### A cut's English is the English of the words it plays

A card's English is picked on its own from the part of the transcript the card covers, through the word links, so a cut's English is the translation of exactly the words it plays. English taken from outside the card's time span (60 or more characters of it) is never used. Every card, staged or cut, shows the English for its words (see Timeline Cards: the editor: The English a cut shows).

### Footage-in works most urgent first, within the site's daily budget

Lining up the English with the original works through what is new in the background, most urgent first:

- an English selection a person is waiting on, ahead of everything;
- the paragraphs on screen in an open transcript (up to 40, asked again as the person scrolls); closing or switching transcript withdraws them unless someone is waiting on one; an English transcript asks for nothing;
- a clip selected on the lane, quietly; about 1.5 seconds after the lane head moves to another cut or the cut list changes, the cuts within 12 of it that show an exact English;
- then everything else.

Translating, lining up the English with the original and the first sort count against the site's one daily budget for the assistant, in money (see The whole product: The assistant). The episode's footage shows what footage-in has spent so far this day, what is left of the day's budget, and what is waiting for the next day's. Footage-in never fails for lack of budget: when the day's budget is spent, that work waits, every waiting selection falls back to Approximate at once, the interview says it is waiting for the next day's budget, and the work carries on by itself when the new day's budget opens. Work a person is waiting on is always taken before work running on its own.

When the assistant is off or unavailable, lining up stands still with "Assistant is not available on this server (<why>)", waiting selections fall back to Approximate, and it starts again by itself within about a minute of the assistant coming back. When the assistant's own provider has run out for now, it pauses with "the server's Assistant budget is spent for now". When lining up gets no answer at all, waiting selections fall back to Approximate and the person is told that no answer came. Work waiting or under way carries on after the server restarts; a selection waiting when the server stops is told "the server is stopping". A new line-up shows on the page without reloading.

### Word-link quality is measured before another way of linking is used

The quality of word links is scored against a hand-checked set of paragraphs. Any other way of making word links, including one that works without the assistant, is scored on the same paragraphs, and is used only if it does at least as well.

#### Lessons

- Met: CFI-084, CFI-085, CFI-086, CFI-087, CFI-088.

## Running on its own, with a hand on every decision

### Clips dropped in become an interview ready to cut

A person drops an interview's clips (camera files and sound recordings, any number, of one interview or of a whole day) onto the episode in Timeline Cards, and does nothing more. Once clips are in, the product makes, on its own and for each interview, with no step started by hand and no editing program open:

- the grouping into interviews, sessions, people and devices;
- every take lined up by its sound, and the multicam;
- the interview's sound, playing in both ears;
- the transcript in the language spoken, in paragraphs with permanent addresses, interviewer questions and chatter marked;
- English for every paragraph not in English;
- the time of every word, in the interview's own timecode;
- the links between the English and the original words;
- a small preview, a listening copy and a waveform;
- and, last, the themes the assistant proposes and the first sort of every paragraph into them on the board, on its own; the proposal stays beside the board, and a person can drop, rename or add themes and sort again, or start from an empty board (see Timeline Cards: the board: What the assistant may do).

Each piece starts as soon as what it needs is ready, and none waits for a person to start, order or repeat it. The heavy work (lining up, transcribing, previews) is done on a computer of the studio's that is able and free (see Work shared out across the computers). What is dropped survives the page closing, the computer restarting and the network dropping; nothing is done twice and nothing is lost. When the interview is ready, it is ready to cut.

- Who: anyone signed in who can open Timeline Cards.
- Ways in: dropping clips onto the episode in Timeline Cards; footage brought in from camera and recorder cards reaches the same place on its own (see The Footage Sorter and camera cards: Sorting into shoots, people and cameras).
- When the Footage Sorter and camera cards is off: clips are only dropped in by hand.
- When the assistant is off: everything that does not need the assistant is still made (grouping, lining up, the multicam, the sound, the transcript with word times, paragraphs at pauses, the preview); questions, chatter, English, word links and the first sort are left for a person, and each interview says which.

### Every decision is shown and can be set by hand

Every decision the product makes on its own between clips arriving and the board being ready is shown on the interview's page with its value and how it was reached, and each one can be set by hand there:

| Decision | Written under |
|---|---|
| which clips are interview takes | "The product decides which clips are interview takes and says why each other clip was left out" |
| where sessions break | "A day with several interviews is split into sessions" |
| which person an interview belongs to | "The product decides which person each recording belongs to" |
| the names of the interview, multicam and transcript | "The interview's names are chosen on its own" |
| which device a recording belongs to | "Recordings are sorted into cameras and recorders by their names" |
| each device's clock | "Each device's clock is chosen on its own and shown" |
| the reference device and the interview's sound | "The product chooses the device every other device is lined up against", "The interview's sound is always the recorder's" |
| how the angles line up | "Every take is lined up by sound to within a frame", "Every camera piece is checked against the sound along its whole length" |
| the order of the angles | "The product decides the order of the angles" |
| the frame rate and drop-frame | "Each interview's frame rate and drop-frame are chosen on its own" |
| the starting timecode of the words | "Word times count from the interview's own starting timecode" |
| one-sided stereo made one-channel | "One-sided stereo sound is made to play in both ears" |
| where the interview begins | "The interview starts at the crew's first question" |
| the picture the preview shows | "Which picture the preview shows" |
| each interviewee's colour | "Each interviewee is given a colour" |
| the language of each stretch, and the main language | "The language of every stretch of speech is decided on its own", "Each recording's main language is decided on its own" |
| who is speaking | "The product decides who is speaking" |
| whether a stretch is missing, and its text | "Nothing said is missing from a transcript" |
| whether a recording is transcribed again | "A recording already transcribed is not transcribed again" |
| how Chinese is written | "Chinese is written in Traditional characters as Taiwan writes it" |
| where paragraphs break | "The product breaks each transcript into paragraphs by meaning" |
| which lines are questions, and which paragraphs are chatter | "The product marks which paragraphs are the interviewer's questions", "Off-topic chatter is set apart" |
| the English of each paragraph | "Every paragraph not in English gets English" |
| the word links | "English and original are linked phrase by phrase on their own" |
| the themes and the first sort | Timeline Cards: the board |

A value set by hand is marked as set by hand, is never overwritten by a later automatic pass, and can be handed back to the product, which then decides it again. Changing a decision redoes only what depends on it, on its own, and never asks for a step to be started. The whole set of decisions for an interview is kept with it, so making it again gives exactly the same result without measuring again.

- Name and search words: the interview's page. Search words: interview, multicam, angles, sync, transcript, overrides.

### What a person sees while footage is processed

The episode lists every interview, each with what is done, what is under way and what is waiting, and any step that takes more than a few seconds shows live progress for each interview. Anything that cannot be done is shown on that interview in plain words, with what a person can do about it, and the rest carries on. Opening an episode lists every transcript in it, and names every file it could not take, with the reason.

- Name and search words: the episode's footage. Search words: footage in, processing, progress, interviews, transcripts.

### Footage-in works whichever computers the studio has

Getting footage ready works on the studio's Windows and macOS computers alike, and its pages are reached like every other page of the product, by people signed in.

- Windows and macOS: no difference a person meets; the heavy work prefers a computer with a graphics card.

#### Lessons

- Met: CFI-089, CFI-090, CFI-091, CFI-092, CFI-093, CFI-094, CFI-095, CFI-096, CFI-097, CFI-098, CFI-099.

## Footage files and files made from them

### A dropped file is found where it already is

A file dropped on a page gives the page its name and size but never where it lives. A dropped recording is found on the studio's storage by its name and size and used where it is; nothing is copied or moved to process it. If it is not there, the person is told, per file, to put it on the studio's storage and drop it again. For each dropped file the page shows whether it was found, and whether it still needs a transcript or a preview.

### Nothing made from a recording can harm it

Files made from a recording (one-channel sound, previews, listening copies, waveforms, transcripts) appear whole or not at all: a half-made file is never seen under its final name. A person's own files are never deleted, and an original recording is never changed. Every name the product makes from a title or a source name fits in 255 bytes, cut on a character boundary keeping its start, a short fingerprint and its id, so it can be written on any NAS. Any number of files with long names can be processed together, and what a batch finished survives a crash.

### Every interview gets a small preview exactly as long as its sound

Beside each interview's sound the product makes a small preview: 480 lines tall keeping the picture's shape, at the multicam's frame rate, with a fresh full frame at least every second so it can be scrubbed, mono sound from the camera, exactly as long as the interview's sound, black before and after the picture, and lined up with the sound from its first frame. Several camera pieces are laid over one black background, each fitted to the first one's shape, their sounds mixed. A graphics card is used when one can be. Raw camera files are taken from their proxies. A listening copy and a waveform of every recording are made as soon as its sound is final, before anyone opens the editor, in bounded memory for a recording of any length, so several at once cannot exhaust a computer. A preview already there is kept unless a person asks for it to be made again.

- By hand: a person can have the preview made again from the interview's page.

### A finished preview is checked against the sound

After a preview is made its sound is compared with the interview's sound at 5 points inside each piece. The person is shown the offset in milliseconds, with a clear warning when it is off by more than a frame (1/30 second), or that no clear match was found. A preview that is off is kept, with the warning shown on the interview and on its cards, and a person can have it made again.


### A preview that cannot be made never stops anything else

Every recording without a preview gets one plain reason (not a multicam, its sound check failed, where its clips sit cannot be read, and so on), and the others carry on. The person sees how many previews were made, how many were already there and how many failed.

#### Lessons

- Met: CFI-100, CFI-101, CFI-102, CFI-104, CFI-105.

## Bringing the studio's existing transcripts in once

### The studio's existing transcripts are brought in once with every paragraph's address

The transcripts the studio already holds are brought in once, each into its interview's one transcript file. Every paragraph keeps the address it already has, so every existing cut list still points at the right paragraphs. In an existing bilingual transcript, the line with the highest share of Chinese characters is the original, provided at least 20% of it is Chinese; for a language without Chinese characters (such as Vietnamese), when a paragraph has two or more lines and the last does not look English, the last is the original. The other lines are the English. A line of question marks stays a question mark, and the readable copy is written from the file.

Each existing transcript is tied to its recording, in this order:

1. a pairing of that transcript to a recording written down by a person, or "skip this transcript", whose cards then show as skipped;
2. the pointer an excerpt carries to the transcript it was taken from (see "A transcript taken from another episode");
3. the recording with exactly the transcript's name within the episode (an online-call transcript only matches an online recording, and the other way round).

A transcript tied by none of these is reported as "transcript not linked" and kept. The recording whose words hold the most of its paragraphs (at least 3, so one interviewee's different shoot days are not mixed up) is offered as the likely match, for a person to accept; a montage source folder holding exactly one transcript is offered as that clip's. Nothing is tied by a resemblance of names alone, and an ambiguous match is reported, never guessed. Each recording is classed as interview, montage or cannot tell, shown on the episode's footage.

- On its own: which recording each existing transcript belongs to, by the order above.
- By hand: a person can pair a transcript with a recording, accept an offered match, or skip a transcript. The pairing is kept through every later pass.

### Every existing paragraph is placed in its recording

Every paragraph brought in, of any length and hand-corrected ones included, gets timing in its recording, even when its words differ slightly from the words heard. Each recording's own word-timed transcription is made first if it has none. A paragraph is found by its last line (for a Mandarin interview, the verbatim Chinese), ignoring punctuation, spacing, letter case, highlight marks and polished English punctuation, with traditional and simplified characters counted the same:

- The first exact occurrence wins, at full confidence. The same paragraph placed twice is pointed out.
- Otherwise the closest stretch is taken if it is at least 80% alike (the earliest of equally good stretches), trimmed so a stray echo cannot pull the start early, and marked as a loose match with its confidence.
- Below that, every other word source the studio holds for that recording is tried (a subtitle export, a transcription made in the editing program), compared in that source's own time base, and the one that places the most paragraphs is used for the paragraphs it alone can place. A span placed only from subtitle lines can run several seconds long, so it is marked approximate wherever it is shown or trimmed, and is never cut short of its quote.
- A paragraph that still cannot be placed is kept and listed, with the closest stretch of the recording and how alike it was.

Where only subtitle lines exist for a recording and no transcript, paragraphs are made from them by breaking at a silence of 2.0 seconds, at the first sentence end after 8 seconds, and always at 20 seconds; a paragraph with at least 20% Chinese characters is treated as Chinese, and each gets an address made from its text so it stays the same between opens.

The interview's page says, per recording, which word source placed its paragraphs.

- On its own: where in the recording each existing paragraph sits, and which word source placed it.
- By hand: a person can place a paragraph by hand by choosing its stretch. A placement set by hand is kept through every later pass.

### A transcript taken from another episode times and plays from its source

An excerpt of an interview reused in another episode times, plays and draws its waveform from the interview it was taken from. Its pointer is followed at most two steps; a pointer that loops or leads nowhere is reported on the episode's footage, and every card of a transcript with no recording shows "no matching clip".

#### Lessons

- Met: CFI-106, CFI-107, CFI-108, CFI-109.

## Montages

### Montage material is downloaded clips with a credit record

Clips gathered for a montage (news clips, for example) are the episode's montage material: each transcribed one can be named, previewed and inserted even when no cut uses it. Montage material holds only downloaded clips with a credit record: interview footage and a clip without a credit record are refused as montage material, and the person is told which and why. A clip downloaded from YouTube carries its channel, title, address and upload date into its transcript as its credit. Its frame rate comes from its file, else 29.97. A clip transcribed again is noticed, and everything that reads the material uses the new words. A quote from the assistant that cannot be placed word for word in a clip falls back to the passage holding its first words.

The episode lists its montage material with each clip's name, id, title, channel, length, speakers, language, frame rate and size.

- By hand: a person can give a clip's credit (source, title, channel, address, date) on the list.
- When YouTube downloads is off: montage material is only what a person drops in, and a clip without a credit record is held back until a person gives its credit.

### A folder of outside clips becomes searchable transcripts with word times

Montage clips are transcribed like interviews, with word times, a readable transcript with paragraph addresses, and English. When a folder is dropped, every video or sound file in it and below is taken, except folders of proxies, of transcripts or of clips already made, hidden folders, and files that are partial, temporary, failed or original copies kept by a download or a conversion. A second file with the same name in one drop is skipped, and the person is told. Before the work starts the person sees how many files there are, how many are already done and how many are to do, and can see the list.

### A montage clip's transcript is laid out by its pauses

A montage clip's paragraphs break where speech pauses, with a "(...)" marker in the gap. Speaker headings appear only when more than one speaker was found. What a person has set by hand is kept when the clip is transcribed again (see "A person's edits are never lost to an automatic redo").

#### Lessons

- Met: CFI-110.
