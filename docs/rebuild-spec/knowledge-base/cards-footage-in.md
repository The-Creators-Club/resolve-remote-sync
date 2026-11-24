# Timeline Cards: footage in, ready to cut: what real use taught

104 lessons. Each is one rule the product can be tested against: what a person saw (the heading), why it happened, and what the product must do. Kinds: *given* is a fact about something the studio has whatever is built; *ruling* is the owner's decision; *situation* is something the product must survive.

## Cameras, sound recorders and their clocks

### CFI-001: Camera and recorder clocks are wrong by minutes, sometimes by years.
- Why: The Sony ran 283 to 689 s slow every shoot, recorder clocks reset to 2000 or 2021, one file sat 44 minutes off, and copies can take the copy date.
- Must: Angles and sound are placed by their audio, searching far enough to find a source an hour from its file time, and never by clock or file date alone.
- Kind: given

### CFI-002: A Blackmagic RAW file's creation date is when it was copied, not shot.
- Why: BRAW files carry the ingest time as their creation date, so it cannot place clips in time, while their timecode can.
- Must: Blackmagic RAW clips are placed in time by timecode or audio, never by the file's creation date.
- Kind: given

### CFI-003: Laying clips out by timecode squeezed a 50-minute session into 29 minutes.
- Why: Some cameras run record-run timecode, which stops while paused; other cameras' file creation time keeps wall clock to 1 s, and two cameras differed by 154 s.
- Must: Each camera is placed by free-run timecode or creation time, chosen per camera, against one shared zero, keeping real pauses as gaps.
- Kind: given

### CFI-004: Blackmagic file names made every clip look like its own camera.
- Why: Blackmagic cameras put the date and time inside the file name, so stripping a trailing take number leaves a name unique to each clip.
- Must: Clips are grouped into cameras correctly for Blackmagic, Sony and every other naming scheme found on real cards.
- Kind: given

### CFI-005: Field recorder files can peak above full scale and clip when converted.
- Why: Recorder files in 32-bit float peaked at +1.8 and +2.2 dBFS; written to 24-bit as they were, every peak above 0 dBFS clips.
- Must: Float recorder audio is lowered so its peak lands at or below -1 dBFS before any fixed-point write, and no output sample clips.
- Kind: given

### CFI-006: The field recorder puts one microphone on one side of a stereo file.
- Why: The owner: "zoom audio is ALWAYS only one channel on stereo"; the dead side still peaks -57 to -59 dBFS and one click can reach -18 dB.
- Must: Recorder sound is folded to mono from the louder channel by average level, a channel peaking under -30 dBFS counts as dead, and the original is kept unaltered.
- Kind: given

### CFI-007: Two recordings of one online interview drift up to 0.6 s apart.
- Why: The local recording carried a constant whine; the clean call recording drifted 0.2 to 0.6 s against it, so one fixed offset could not align them.
- Must: Swapping in a cleaner recording aligns it piece by piece, keeping every word and cut within 5 ms over almost the whole interview.
- Kind: given

### CFI-009: Four interviews were silently built on camera scratch audio.
- Why: Misfiled recorder files left the build on camera sound; the owner: "the zoom recorder should always be priority, it's better than the lav".
- Must: The recorder is always the interview sound; with none found the build stops and says where to look, continuing only on a recorded, explicit override.
- Kind: ruling

### CFI-010: An interview "with no recorder audio" usually has its recorder file misfiled.
- Why: Recorder files with reset clocks sat under another interviewee or loose; the owner asked to transcribe "only files over 7 minutes long. And only loose wavs" and match by content.
- Must: Before an interview is built without recorder sound, loose recordings over 7 minutes are matched to it by spoken content and any match is reported.
- Kind: ruling

### CFI-008: A lav or camera track can be dead for a whole interview.
- Why: Lavs recorded 44 to 60 minutes of flat -77 dBFS noise and cameras recorded silence; matching against them scored 0.02 to 0.07, which no gain fixes.
- Must: A silent or near-silent source is detected and never used as the sync reference or the interview sound; another is chosen and the choice is shown.
- Kind: situation

### CFI-011: The recorder stopped 28 minutes into an 80-minute interview.
- Why: The recorder file ended early, leaving most of the interview without its main sound.
- Must: Where the recorder stops early, the interview carries the best camera sound for the rest rather than going silent, and says so.
- Kind: situation

### CFI-012: A recorder covering only an interview's second hour matched nothing.
- Why: The recorder started late, so against the first camera file it scored 0.018 and was excluded; against the second camera file it scored 0.877.
- Must: Recorder audio is matched against every camera file of the interview, and a recorder covering only part of it is still placed.
- Kind: situation

## Frame rates

### CFI-013: Blackmagic cameras record true 30.000 or 24.000 fps; Sony records 29.97 or 23.976.
- Why: The Pyxis records true 24.000 beside an FX3 at 23.976; Resolve retimes a 30.000 clip onto 29.97 by time, so frames sit up to half a frame off.
- Must: Mixed-rate angles are reported on arrival and stay in sync without drift, and a one-frame mismatch from a true-rate file is not called a broken build.
- Kind: given

### CFI-014: Mixed frame rates and misread drop-frame timecode drift a multicam out of sync.
- Why: True 30 treated as 29.97 drifts 1.8 frames a minute; 29.97 drop-frame timecode read as non-drop drifts about 50 frames in 25 minutes.
- Must: Every clip's frame rate is handled exactly, drop-frame timecode is decoded as drop-frame, and a mixed-rate shoot states what drift it costs.
- Kind: given

### CFI-015: An interview's picture drifted from its own sound, in sync at one instant only.
- Why: A Blackmagic camera with off-speed on put a 29 fps sensor into a 30p file, so picture ran 3.45% fast; Resolve shows "Camera FPS 29" beside "Shot Frame Rate 30".
- Must: Clips whose sensor rate differs from their file rate are flagged on arrival with the speed correction (about 96.7%), and never synced by their own audio.
- Kind: given

### CFI-016: New material with no stated frame rate defaults to 29.97 drop-frame.
- Why: Every studio interview and timeline measured 29.97 drop-frame, and the owner set it as the default.
- Must: Timelines and clips with no stated rate default to 29.97 drop-frame, and a rate a file states is always kept.
- Kind: ruling

### CFI-017: New cuts silently used coarse timing and 25 fps though word timing existed.
- Why: When the word timing could not be reached, a new cut list fell back to subtitle timing and a default rate for all 258 cards, with no warning.
- Must: Any clip whose word timing or frame rate is missing or guessed is named, with a warning, before a cut list is made from it.
- Kind: situation

## Facts about Resolve: rates, multicams, timecode

### CFI-018: Resolve clips keep the frame rate the project had when they were imported.
- Why: WAVs imported into a 24 fps project stay 24; positions counted in 29.97 timeline frames put 11 of 16 interviews 0.4 to 25 s out and stretched a timeline 401 s.
- Must: Every position sent to Resolve is computed in that clip's own rate, and each build is read back in seconds and fails loudly beyond one frame.
- Kind: given

### CFI-020: Resolve's scripting has no way to create a multicam clip.
- Why: A multicam needs Resolve's "Create New Multicam Clip Using Selected Clips" dialog, which scripting cannot call, so each interview took a manual step or about 46 s of driven clicks.
- Must: Multicam creation never assumes Resolve offers a scripted way, and any step left to a person in Resolve is named exactly.
- Kind: given

### CFI-021: A two-camera interview came out of Resolve as a multicam with 59 angles.
- Why: Resolve's multicam-from-selected-clips makes every FILE an angle, and its scripting cannot build, repair or move items in a multicam.
- Must: A multicam built from cameras that split recordings into many files has exactly one angle per camera.
- Kind: given

### CFI-022: Resolve's scripting cannot reach multicam angles or set a transcription language.
- Why: Scripting exposes no multicam angles, and setting the transcription language returns false for every value, so auto-detect picked English for Mandarin interviews.
- Must: Nothing that prepares footage depends on these calls, and anything Resolve cannot do is done another way or reported, never silently skipped.
- Kind: given

### CFI-023: A Resolve multicam has no media file and no frame rate of its own.
- Why: A multicam is a sequence of angles: its rate and start timecode live only in Resolve's record, and its rendered audio has no video to read a rate from.
- Must: A multicam's rate and timecode come from Resolve's own record of it, and its audio-only preview says plainly there is no picture.
- Kind: given

### CFI-024: Resolve's audio-only render of a one-microphone multicam plays in one ear.
- Why: Resolve's Audio Only preset writes a single-input multicam as stereo, sound left and only converter noise right.
- Must: Interview audio with exactly one channel above about -60 dBFS is made true mono before anything uses it; a real second microphone is kept.
- Kind: given

### CFI-025: A multicam's audio render came out 13 minutes long instead of 16.
- Why: In and out marks set inside a Resolve multicam limit what it renders, so the export was truncated without warning.
- Must: An audio render of a multicam always covers its full length, with any in and out marks cleared first.
- Kind: given

### CFI-026: Word times for a plain audio recording landed an hour late.
- Why: In Resolve a plain WAV starts at 00:00:00:00 while timelines and multicams start at 01:00:00:00; mixing the two bases left 73 clips with no text.
- Must: Word times are measured from each recording's own start timecode, and two timings of one clip are combined only after checking they share a time base.
- Kind: given

See also, filed under another capability:

- RSV-111 (Resolve on the editor's computer): Resolve projects start at 24 fps or at the first raw clip's rate.

## Grouping clips and building the multicam

### CFI-029: Interview multicams start at the first question and hold only interview takes.
- Why: The owner: "cut them to start when the first question is asked"; bins held b-roll and b-camera takes, once 159 short takes after the recorder stopped.
- Must: One multicam per interviewee, starting at the first question and ending at the earlier of the last interview take and the end of its sound, b-roll left out.
- Kind: ruling

### CFI-035: Re-syncing a multicam moves the picture, never the edited sound.
- Why: All editing is cut against the sound; the owner: "the audio itself must not move an inch... only the video can be moved", with the recorder's live channel as mono.
- Must: A sync repair shifts only picture on every angle, and every audio clip keeps its exact position and in-point, checked before and after.
- Kind: ruling

### CFI-036: Swapping in better audio must not change an interview's length.
- Why: The owner: "sync all the zoom audio into the multicams WITHOUT changing the length", and no re-transcribing "because the audio timing is the same".
- Must: Replacing an interview's sound keeps its length to the frame and every cut span intact, reuses its word timing, levels the new sound, and leaves correct angles untouched.
- Kind: ruling

### CFI-038: Each interviewee's multicam wears that interviewee's colour from the plan.
- Why: The owner colours each interviewee's cards in the plan and wants their multicam clips in Resolve to carry the same colour from the start.
- Must: Every interviewee's multicam clip shows that interviewee's plan colour in Resolve from the moment it is made.
- Kind: ruling

### CFI-027: A folder can hold someone else's interview, and one recording two interviews.
- Why: One person's folder held another's whole interview, a tape held a husband's then his wife's interview, and one interview came in two sessions three hours apart.
- Must: Grouping shows who introduces themselves and when, and a person can move a file to another interviewee, split a recording at a time, or join sessions.
- Kind: situation

### CFI-028: The same interviewee's name arrives romanised in different orders and spellings.
- Why: "Huang Chi-wen" and "Chih-Wen Huang" are one person, while "Taipei Zookeeper" matched "Taipei Zoo Spokesperson" exactly at a 0.50 threshold.
- Must: Grouping by person survives reordered and re-spelt romanisations, and a borderline name match is shown for a person to confirm before anything is filed.
- Kind: situation

### CFI-030: The crew's opening question is often too quiet to hear.
- Why: With the question off-mic, the interview start fell on the answer with a 1.5 s lead, and had to be moved earlier by hand to include it.
- Must: An interview's start includes the opening question even when faint, and a person can move the start without rebuilding anything.
- Kind: situation

### CFI-031: Switching angle in an interview multicam must never change the sound.
- Why: A camera microphone sounds different from the recorder or lav, so sound jumping between them as angles switch is jarring.
- Must: Every angle of an interview multicam carries the same best microphone.
- Kind: situation

### CFI-032: Angles placed by clock were off by up to a second, take by take.
- Why: Camera clocks differ by a constant of minutes, and creation times jitter by a second per take.
- Must: Every take of every angle is synced to sound within a frame, and a take that cannot be matched is moved by the agreed camera offset, not left behind.
- Kind: situation

### CFI-033: A camera with no usable sound can only be placed by clock or picture.
- Why: Silent angles were placed from that camera's clock error on other shoots (stable at 148-151 s) or by picture motion; clock placement once opened on a long empty stretch.
- Must: Cameras found per session are shown, an angle placed without sound is marked unverified for a person to check, and no multicam opens on an empty stretch.
- Kind: situation

### CFI-034: A one-camera stop-start event laid out by the clock is mostly empty.
- Why: A press conference shot on one camera, laid out by wall clock, opened with 30 s of picture in 80 s of nothing.
- Must: A single camera that stopped between takes can be laid out with its takes back to back in recorded order.
- Kind: situation

### CFI-037: Better audio shorter than the old left a silent tail under a cut.
- Why: One interview's recorder file ended 0.93 s before the furthest cut, so that cut's last second went silent.
- Must: An audio replacement that cannot cover every span the cuts use either fills the tail from the old sound or refuses; it never leaves silence.
- Kind: situation

See also, filed under another capability:

- RSV-125 (Resolve on the editor's computer): Resolve's clip colour names mislead, and the owner bans "Brown".

## Facts about Resolve's own transcription

### CFI-040: Resolve's own transcription leaves holes and garbles specialist words.
- Why: It skipped 20 to 50 s stretches of real speech, once 3:55, with no sign, mangled 代孕 as 待遇, and took 44 to 90 s per clip.
- Must: No transcript the editor relies on comes from Resolve's transcription; any Resolve transcript brought in is checked for holes against an independent one.
- Kind: given

### CFI-043: "(Speaking In Foreign Language)" in a Resolve transcript means the wrong language.
- Why: Mandarin transcribed as English gave 26 minutes of placeholders, 334 words, against 3,661 in Mandarin; "(Blank Audio)", "(Music Playing)" and one token repeating for minutes mean no speech.
- Must: A placeholder-filled transcript is treated as wrong-language and redone, and no cut is placed in a placeholder or repeated-token span.
- Kind: given

### CFI-044: Resolve writes Mandarin in Simplified characters and ignores sentence ends.
- Why: Resolve emits Simplified while the studio works in Traditional, mishears names and terms, and breaks cues across sentences; byte comparison against Traditional words failed.
- Must: Mandarin text is compared in either script or a mix, and no card's text or boundaries depend on Resolve's transcription.
- Kind: given

### CFI-045: Resolve's scripting cannot read back a clip's transcription in full.
- Why: The transcription property stops after 10 lines; regenerating subtitles from audio re-transcribes angle 1's camera mic and recovered about 45% of speech, with 130-second holes.
- Must: Transcripts used for cutting carry every word with its time, never a scripted read-back or a regenerated subtitle pass.
- Kind: given

### CFI-046: Resolve's transcription sometimes crushes a sentence into one millisecond.
- Why: Two of ten clips had 1 ms cues carrying full sentences, cues starting before the last ended, and rates up to 46,000 characters per second; re-transcribing did not fix one.
- Must: Any transcript brought in is swept for tiny cues with real text, backwards starts and absurd rates, and those spots are flagged before a cut uses them.
- Kind: given

### CFI-048: Spans timed from Resolve's subtitle cues run up to six seconds long.
- Why: Of 435 spans timed from exported cues, none ran shorter than word timing and 147 ran longer (worst 5.94 s, 23% by over 2 s); Mandarin cues are long.
- Must: Spans timed only from subtitle cues are marked approximate wherever shown or trimmed, and never cut a quote short.
- Kind: given

## Speech-to-text: rulings

### CFI-049: Transcripts and word timing come only from the product's own speech-to-text.
- Why: After repeated holes in Resolve's transcripts the owner: "we never want to use resolve", and "jettison the srt and resolve transcripts"; names are fixed by hand instead.
- Must: Text and word timing come from one speech-to-text run per recording; Resolve's transcription is never run, offered or reconciled, and each transcript names what made it.
- Kind: ruling

### CFI-050: Transcribing clips must never need Resolve open.
- Why: The owner: "Why does [the speech-to-text] need Resolve open? It just runs locally on the machine." Touching Resolve's scripting needlessly also risks killing it for the session.
- Must: Transcription and the clip facts it needs work with Resolve closed and never connect to Resolve at all.
- Kind: ruling

### CFI-051: When paid transcription runs out of credit, transcription carries on locally.
- Why: The owner's rule: transcribe with the paid cloud service first, and fall back to a local engine on the studio's GPU when its credit runs out.
- Must: Transcription continues on the local engine when the paid service refuses for lack of credit, and each transcript says which engine made it.
- Kind: ruling

### CFI-053: Language is detected per stretch of speech, never per file or from a name.
- Why: The owner: "we should just enable language detection", interviews switch language "so it should be able to cope"; one-language captioning skipped a bilingual film's Chinese.
- Must: Each stretch is transcribed in the language spoken there, the line at each switch is kept, and no language is chosen from a person's name.
- Kind: ruling

### CFI-057: Each speaker is transcribed in their own language, and an interpreter can be left out.
- Why: One student spoke Vietnamese through an interpreter; the owner: "I only want her bits, I don't want the translation".
- Must: Each speaker's speech is transcribed in its own language, and an interviewee's own words can be kept while an interpreter's lines are dropped.
- Kind: ruling

### CFI-058: Every transcribed clip has per-word timing, older ones included.
- Why: The owner: "how is there no word level timings it makes no sense"; an episode transcribed earlier had none, and two clips side by side differed.
- Must: Every interview has word timing by default, older interviews lacking it are filled in on their own, and a clip without it says why.
- Kind: ruling

### CFI-052: Nothing spoken may be missing from a transcript, quiet questions included.
- Why: The owner: "It matters HUGELY that nothing be missing"; a silence filter dropped off-mic questions, about 14 minutes on one interview, 0.4 to 8 minutes on others.
- Must: Any stretch over 3 s where speech is audible but no words came back is transcribed again, so the interviewer's quiet questions are kept.
- Kind: situation

### CFI-054: Forcing Mandarin on a mixed batch turned English interviews into Chinese.
- Why: An English speaker with a Chinese name was batched as Mandarin; forced speech-to-text silently translated her into Chinese at full confidence, then cards translated it back.
- Must: No language is forced across a batch, a forced run's confidence is never trusted, and each transcript's language is checked before anything is built from it.
- Kind: situation

### CFI-055: Crew asides inside a long run of the other language must not split it.
- Why: Short crew remarks like "Thank you." or "Cut." sit inside long Mandarin runs and would start false language stretches.
- Must: A stretch under 3 s in a language neither neighbour speaks is absorbed into its neighbours.
- Kind: situation

### CFI-056: A misdetected language makes the speech-to-text invent text in random languages.
- Why: An English interview came out as a jumble of other languages, and forcing one language on a multilingual speaker turns the others into fluent nonsense.
- Must: An editor can set an interview's language and re-transcribe it, and each transcript shows which language it was made in.
- Kind: situation

## Speech-to-text: facts and situations

### CFI-059: Speech-to-text word times do not mark where a word starts in the audio.
- Why: Over two interviews a word's start time sat a median 88 ms from the nearest dip in the audio, against 74 ms for a random moment.
- Must: No transcribed word time is treated as a frame-accurate cut point; anything needing one measures the audio itself.
- Kind: given

### CFI-060: Mandarin timed words arrive one character at a time.
- Why: Speech-to-text splits Mandarin by sound, so names like 林保署 and words like 颱風 arrive as separate characters.
- Must: Anything working on timed Mandarin words regroups characters into real words first, never assuming one timed word is one dictionary word.
- Kind: given

### CFI-061: Mandarin speech-to-text writes soundalike characters, hiding search terms.
- Why: A search for a key term found nothing because the transcription wrote 放 as 犯 or 繁 throughout; the term existed only in the question sheet.
- Must: Transcript search finds soundalike spellings of a Mandarin term, so a misheard word never hides the passage.
- Kind: given

### CFI-062: A batch transcription silently skipped 16 of 51 clips.
- Why: A first pass over 51 downloaded clips left 16 without a transcript and reported nothing; a re-run picked them up.
- Must: After a batch, every clip is checked for a transcript, and each missing one is retried or listed.
- Kind: situation

### CFI-063: Re-running transcription over a finished folder should cost seconds, even after copying.
- Why: Folders are re-run often, and the same file copied to another disk is the same clip; transcribing it again wastes minutes per hour of audio.
- Must: A re-run skips every clip already transcribed, including the same file copied elsewhere, and finishes in seconds.
- Kind: situation

### CFI-064: A wrong speaker label on narration is worse than no label.
- Why: Over a narrator with archive audio a second voice was heard but owned no word, while a news studio clip rightly got four speakers.
- Must: A word gets a speaker only where that voice clearly owns it, within half a second; otherwise it stays unlabelled.
- Kind: situation

### CFI-065: A failure in speaker detection must cost only the speaker labels.
- Why: A missing licence, download or undecodable file in speaker detection would otherwise throw away a transcription that had already succeeded.
- Must: When speaker detection fails, the transcript is still written without speakers, and the reason is recorded and shown.
- Kind: situation

### CFI-066: Short cuts showed words not in the edit, and audible words greyed out.
- Why: Word timing was inexact, so tightly cut cards carried extra words, and greyed-out words were usually the last ones actually heard.
- Must: A card shows exactly the words audible within its cut, with none heard greyed and none unheard shown.
- Kind: situation

### CFI-067: Counting seconds of gap overstated missing speech a hundredfold.
- Why: Across ten multicams (6h04m), reference cues over transcript gaps suggested 9m40s missing; most gaps were silence or room chatter, and about 40 characters were really lost.
- Must: A missing-speech check measures missing text (is the reference text anywhere within about 90 s), never seconds of overlap.
- Kind: situation

### CFI-068: Comparing a transcript's end with the clip's length only finds cut-off endings.
- Why: That check flagged a clip 11 s short that was only room tone, and passed every clip whose damage was in the middle.
- Must: A transcript health check looks for holes and bad timings throughout the clip, and an end-time check is labelled a tail check only.
- Kind: situation

## Chinese script

### CFI-069: Mandarin text reads as Taiwan writes it, in Traditional characters with 台.
- Why: The owner: "we want 滑鼠/影片"; the house style is Taiwan phrasing and 台灣 with 台, while speech-to-text emits Simplified and standard conversion turns 台 into 臺.
- Must: Every Mandarin transcript, word, cue and card is Traditional with Taiwan phrasing and 台, identically in search; text in another language is never converted.
- Kind: ruling

### CFI-070: A transcript and its timed words must be spelled identically.
- Why: Script conversion depends on surrounding words; converted per word it gave 類型 where the sentence gave 型別, 364 divergences across 13 of 16 transcripts.
- Must: Script conversion runs over whole sentences and is mapped back onto the words, so text and timed words match character for character.
- Kind: situation

### CFI-071: English words from separate timed pieces were glued together as "readyfor".
- Why: Joining timed pieces with nothing between them suits Chinese but glued English words across the joins.
- Must: Timed pieces are joined with a space unless the join falls between Chinese or Japanese characters.
- Kind: situation

## The transcript and its English

### CFI-072: A transcript, its translation, word times and word links are one file.
- Why: The owner: "make it one file where everything is together", with a readable copy any clip's transcript can be opened and browsed from.
- Must: Correcting a word never detaches its timing or English, a readable Markdown copy is always kept in step, and old transcripts import keeping every paragraph reference.
- Kind: ruling

### CFI-073: Each interviewee has exactly one transcript.
- Why: A re-paragraphed copy saved beside the original doubled the English on every card; the owner: "just delete the original and make this the new single transcript".
- Must: Each interview has exactly one transcript, reworking its paragraphs updates that one in place, and a second copy is flagged, never merged in.
- Kind: ruling

### CFI-074: A transcript reads as meaning-based paragraphs with questions marked and full English.
- Why: The owner wants paragraphs by meaning, the interviewer's question as a heading, each paragraph translated "NATURALLY and COMPLETELY", and a reference per paragraph.
- Must: Each paragraph carries the question it answers, its verbatim original, its full natural English, and a reference that survives edits and renames.
- Kind: ruling

### CFI-075: A card holds at least two sentences, never a single word or sentence.
- Why: The owner had a speaker's transcript re-paragraphed so that no card held a single sentence or word.
- Must: Transcripts split into cards of at least two sentences, merging shorter fragments into a neighbour and keeping the first one's reference.
- Kind: ruling

### CFI-076: Bilingual transcripts show the English line above the Chinese.
- Why: The owner asked for every Chinese transcript, news reports included, translated "so I can see them english above the chinese".
- Must: Every bilingual block shows English above its Chinese, and adding English never moves a paragraph reference a cut already uses.
- Kind: ruling

### CFI-077: Every interview yields a complete original text and a complete English text.
- Why: The owner asked for "a full ZH subtitle and a full EN subtitle", with likely mishearings flagged using a list of names and terms he supplies.
- Must: Every interview has a complete original and English text, and likely mishearings are flagged against the owner's list of names and terms.
- Kind: ruling

### CFI-078: Adding the English must never correct the transcribed words.
- Why: The owner ruled that no speech-recognition corrections happen in the translation pass, "now and going forward".
- Must: Translating leaves every transcribed word exactly as it was; any change to the words is a separate step a person chooses.
- Kind: ruling

### CFI-079: Speech in any language other than English gets English.
- Why: Italian, French and German cards got no English, and Vietnamese and Indonesian read as English, because only Chinese counted as foreign; the owner: "add translating from any detected language".
- Must: Any non-English language is detected and translated, and real English is never sent for translation and shows its words once.
- Kind: ruling

### CFI-081: Staged cards must show English like cut cards do.
- Why: The owner: "the staged section shows English translations too".
- Must: Every card, staged or cut, shows the English for its words.
- Kind: ruling

### CFI-080: A card's English came from a passage further down the interview.
- Why: Given neighbouring paragraphs as context, the translator copied their English out in order, landing a paragraph or more ahead (once 35 s) while the Mandarin was right.
- Must: A cut's English is the translation of exactly the words it plays; English copied from outside its time span (60 or more characters) is refused.
- Kind: situation

### CFI-082: Throttled translation looked stuck, with no sign why.
- Why: Hundreds of Mandarin cards waited in the translation service's "too many requests" back-off with nothing on screen, and results appeared only after the next edit.
- Must: When translation is throttled or failing the screen says so, and each finished translation appears as soon as it lands.
- Kind: situation

### CFI-083: Two computers overwrote each other's translations.
- Why: Each program read the shared translations once at start and saved its whole copy over them.
- Must: A translation made on any computer appears on every other, and a save never removes another computer's entries.
- Kind: situation

## Word links between the original and the English

### CFI-084: A name or compound must light its whole English as one unit.
- Why: The owner: "the compound splitting would be an issue": 林保署 linked Forestry to 林 and Agency to 保署, and 莫拉克颱風 had Typhoon and Morakot swapped.
- Must: A multi-character name, compound or abbreviation links as one unit with one gloss, any of its characters lights all its English, and no boundary falls inside it.
- Kind: ruling

### CFI-088: Word-link accuracy is measured before any other linker or offline option is used.
- Why: The owner asked about offline models, then "dont build it for offline yet"; first test "the accuracy of word links on a word aligner vs [the assistant]".
- Must: Word-link quality is scored against a hand-checked answer key, and any dedicated aligner or offline option is compared on the same paragraphs before it ships.
- Kind: ruling

### CFI-085: One stray word link must not throw away the whole paragraph's links.
- Why: A compound can straddle a phrase edge, so a link pointing outside its phrase is normal, yet it failed the whole paragraph.
- Must: An invalid link is dropped on its own and the paragraph's other links are kept.
- Kind: situation

### CFI-086: Paragraphs whose word links failed were never asked again.
- Why: Failures were stored as final, so re-runs skipped them; of 1,605 paragraphs 15 failed, a retry fixed 10, and 5 failed because their English was a summary.
- Must: Failed paragraphs are retried on the next run, and any that fail twice are shown with a plain reason such as "English is a summary, not a translation".
- Kind: situation

### CFI-087: A long background run threw away most of its paid answers at a cut-off.
- Why: 392 of about 500 word-link calls ran past a 180-second limit and were discarded after being paid for; with room to finish, 600 paragraphs took about 20 minutes.
- Must: A background batch gives each call room to finish, and an answer already paid for is never discarded for being slow.
- Kind: situation

## Running on its own, with a hand on every decision

### CFI-089: Everything from clips to word links runs on its own.
- Why: The owner: "make the word link pass part of the multicam pipeline ... so that all of this gets done automatically at the end".
- Must: Once clips are in, grouping, sync, multicam, transcript, English and word links all complete with no step started by hand.
- Kind: ruling

### CFI-090: Every automatic guess in footage processing can be corrected by hand.
- Why: The owner: "yes automatic guess can be corrected": a word, a translation, a speaker, an interview grouping.
- Must: Each automatic decision is visible and settable by hand, and a later automatic pass never overwrites a value a person set.
- Kind: ruling

### CFI-091: A long processing step ran ten minutes with nothing on screen.
- Why: Sorting showed no progress for ten minutes, and the owner asked to see transcription progress too.
- Must: Every processing step that takes more than a few seconds shows live progress per interview.
- Kind: ruling

### CFI-092: Clips with no transcript are flagged and can be transcribed from the editor.
- Why: The owner: "flag it, show progress, one trigger", for one clip, every clip, or "clips ACTUALLY USED in the live cut file", on a chosen computer.
- Must: Untranscribed clips are marked; a person can transcribe one, all, or the open cut's, on a computer picked from a list defaulting to the last, with live progress.
- Kind: ruling

### CFI-093: Re-transcription must never overwrite a hand-edited transcript or touch the footage.
- Why: Source footage folders are read-only, and a transcript a person corrected is worth more than a fresh machine pass over the same clip.
- Must: Transcription never writes into source footage folders and never overwrites a hand-corrected transcript unless a person explicitly forces it.
- Kind: situation

### CFI-094: Re-preparing or renaming an interview must not orphan its cuts or translations.
- Why: Cuts and paid translations pointed at the existing paragraphs; respelling 398 words would have orphaned 105 translations, and renaming broke the tie between transcript and clip.
- Must: Re-transcribing, re-paragraphing, respelling or renaming an interview keeps every existing cut's reference and every translation attached, with no new translation paid for.
- Kind: situation

### CFI-095: A corrected transcript left the old words on cuts already made.
- Why: Each cut's words were stored with the cut and refreshed only when trimmed, and changed transcripts were read only at a restart.
- Must: A transcript added or changed shows on every card and saved cut within minutes, with no restart and no edit.
- Kind: situation

### CFI-096: A second speech-to-text pass rewrote clip words, so their English vanished.
- Why: Re-timing interviews with a fresh transcription brought different characters and words (他 heard as 它), and re-cutting 707 clips from it broke their English.
- Must: New word timings only move a clip's edges; its words stay in the transcript's own wording and characters.
- Kind: situation

### CFI-097: Changing how spans are worked out must not silently move cuts already placed.
- Why: Every span in every hand-ordered cut rests on the current rule; a different rule would move cut points across every project unseen.
- Must: A change in how spans are computed alters no placed cut's start or end unless the editor is shown each change and accepts it.
- Kind: situation

### CFI-098: An interview reused from another episode had no timing and no audio.
- Why: An excerpt transcript points at another episode's recording, and its audio only ever lived in that episode's folder; 26 cards came out unmatched.
- Must: An excerpt reused in another episode times, plays and draws its waveform from its declared source; a pointer that loops or leads nowhere is reported.
- Kind: situation

### CFI-099: The editor found no transcripts in an episode's folder.
- Why: Pointed at one episode's folder, the editor read no transcripts at all, with no reason given.
- Must: Opening an episode lists every transcript in it, or says which files it rejected and why.
- Kind: situation

## Footage files and files made from them

### CFI-100: A file dropped on a web page gives its name and bytes, never its path.
- Why: Browsers hand a dropped file's name, size and contents to the page but not its place on disk, and uploading multi-gigabyte video through a page is impractical.
- Must: Dropped media is found on the NAS by name and size; if it is not there, the person is told to put it there and drop it again.
- Kind: given

### CFI-101: A NAS share limits a file name to 255 bytes, not characters.
- Why: A Chinese character is 3 bytes, so a 244-byte news title plus a working suffix hit 256 and the audio was never made, though its waveform showed.
- Must: Every name made from a title or source name fits 255 UTF-8 bytes, cut on a character boundary keeping the start, a hash and the id.
- Kind: given

### CFI-102: Windows refuses command lines longer than about 32,000 characters.
- Why: A folder of news clips with long CJK titles exceeded the 32,767-character limit (error 206) before any work began.
- Must: Processing any number of long-named files on Windows never fails on command-line length, and partial batch results survive a crash.
- Kind: given

### CFI-104: Most interviews had no small listening copy or waveform ready.
- Why: These were made only when a page asked, so a new project had them for just 2 interviews, and working offline offered 2.9 GB of full WAVs.
- Must: Every clip's small listening copy and waveform are made as soon as its sound is final, before anyone opens the editor.
- Kind: situation

### CFI-105: Drawing a waveform held a whole decoded clip in memory.
- Why: Long interview clips decode to gigabytes of audio, and every waveform job kept the whole decode in memory at once.
- Must: Waveforms for clips of any length are made in bounded memory, and several at once cannot exhaust the machine.
- Kind: situation

See also, filed under another capability:

- JOB-037 (Work shared out across the computers): A stale waveform newer than its footage was never remade.

## Bringing the studio's existing transcripts in once

### CFI-106: Existing transcript paragraphs went dead when timed from a second transcription.
- Why: A second transcription of the same audio differs by a character or two per paragraph; 80 to 90% got no timing, and a one-character-off 31-character paragraph scored 0.732.
- Must: On import, every paragraph of any length, hand-corrected ones included, gets timing even when its words differ slightly from the timed words, with honest confidence.
- Kind: situation

### CFI-107: An imported paragraph that cannot be placed says only "text not found".
- Why: Two transcriptions of one interview disagreed on about 40% of paragraphs (309 cards unmatched), and diagnosing six unmatched cards took a long hunt.
- Must: An imported paragraph that cannot be placed is kept, listed, and shows the closest stretch of the recording and how similar it was.
- Kind: situation

### CFI-108: An existing Resolve transcript export had holes of 20 to 30 seconds.
- Why: One interviewee's export missed long stretches, so only 1 of his 155 paragraphs could be placed against it.
- Must: On import, when one word source cannot place a transcript every other source for that clip is tried; an unplaced interview stays listed as "transcript not linked".
- Kind: situation

### CFI-109: Matching clips by fuzzy name landed interviews on the wrong footage.
- Why: Across 6,198 library clips, loose name matching put interviews on YouTube rushes and a music file, and folded news packages sharing a long name prefix into one.
- Must: On import, each transcript is tied to its clip by an explicit pointer or exact name within the episode, and an unknown or ambiguous one is reported.
- Kind: situation

## Montages

### CFI-110: A montage uses only downloaded material, never the studio's own interviews.
- Why: The owner's rule: a montage is news, coverage or archive the product downloaded, with credits, never the studio's interview material.
- Must: Building a montage refuses interview footage and any clip without a credit record.
- Kind: ruling
