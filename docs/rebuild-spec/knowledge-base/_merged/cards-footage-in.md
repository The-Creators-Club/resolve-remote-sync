# Timeline Cards: footage in, ready to cut

## Cameras, sound recorders and their clocks

### CFI-001: Camera and recorder clocks are wrong by minutes, sometimes by years.
- What was going on: The Sony ran 283 to 689 s slow every shoot, recorder clocks reset to 2000 or 2021, one file sat 44 minutes off, and copies can take the copy date.
- What the product must do: Angles and sound are placed by their audio, searching far enough to find a source an hour from its file time, and never by clock or file date alone.
- Kind: 1a
- From: D02-002, P14-034

### CFI-002: A Blackmagic RAW file's creation date is when it was copied, not shot.
- What was going on: BRAW files carry the ingest time as their creation date, so it cannot place clips in time, while their timecode can.
- What the product must do: Blackmagic RAW clips are placed in time by timecode or audio, never by the file's creation date.
- Kind: 1a
- From: M02-050

### CFI-003: Laying clips out by timecode squeezed a 50-minute session into 29 minutes.
- What was going on: Some cameras run record-run timecode, which stops while paused; other cameras' file creation time keeps wall clock to 1 s, and two cameras differed by 154 s.
- What the product must do: Each camera is placed by free-run timecode or creation time, chosen per camera, against one shared zero, keeping real pauses as gaps.
- Kind: 1a
- From: C04-054

### CFI-004: Blackmagic file names made every clip look like its own camera.
- What was going on: Blackmagic cameras put the date and time inside the file name, so stripping a trailing take number leaves a name unique to each clip.
- What the product must do: Clips are grouped into cameras correctly for Blackmagic, Sony and every other naming scheme found on real cards.
- Kind: 1a
- From: C04-056

### CFI-005: Field recorder files can peak above full scale and clip when converted.
- What was going on: Recorder files in 32-bit float peaked at +1.8 and +2.2 dBFS; written to 24-bit as they were, every peak above 0 dBFS clips.
- What the product must do: Float recorder audio is lowered so its peak lands at or below -1 dBFS before any fixed-point write, and no output sample clips.
- Kind: 1a
- From: C06-001, P11-011, D02-023

### CFI-006: The field recorder puts one microphone on one side of a stereo file.
- What was going on: The owner: "zoom audio is ALWAYS only one channel on stereo"; the dead side still peaks -57 to -59 dBFS and one click can reach -18 dB.
- What the product must do: Recorder sound is folded to mono from the louder channel by average level, a channel peaking under -30 dBFS counts as dead, and the original is kept unaltered.
- Kind: 1a
- From: P11-009, D03-002, P13-005, C06-002

### CFI-007: Two recordings of one online interview drift up to 0.6 s apart.
- What was going on: The local recording carried a constant whine; the clean call recording drifted 0.2 to 0.6 s against it, so one fixed offset could not align them.
- What the product must do: Swapping in a cleaner recording aligns it piece by piece, keeping every word and cut within 5 ms over almost the whole interview.
- Kind: 1a
- From: P16-039

### CFI-008: A lav or camera track can be dead for a whole interview.
- What was going on: Lavs recorded 44 to 60 minutes of flat -77 dBFS noise and cameras recorded silence; matching against them scored 0.02 to 0.07, which no gain fixes.
- What the product must do: A silent or near-silent source is detected and never used as the sync reference or the interview sound; another is chosen and the choice is shown.
- Kind: 3
- From: D02-003, M02-051

### CFI-009: Four interviews were silently built on camera scratch audio.
- What was going on: Misfiled recorder files left the build on camera sound; the owner: "the zoom recorder should always be priority, it's better than the lav".
- What the product must do: The recorder is always the interview sound; with none found the build stops and says where to look, continuing only on a recorded, explicit override.
- Kind: 2
- From: D01-007, P11-059, C06-003

### CFI-010: An interview "with no recorder audio" usually has its recorder file misfiled.
- What was going on: Recorder files with reset clocks sat under another interviewee or loose; the owner asked to transcribe "only files over 7 minutes long. And only loose wavs" and match by content.
- What the product must do: Before an interview is built without recorder sound, loose recordings over 7 minutes are matched to it by spoken content and any match is reported.
- Kind: 2
- From: P12-061, P14-035

### CFI-011: The recorder stopped 28 minutes into an 80-minute interview.
- What was going on: The recorder file ended early, leaving most of the interview without its main sound.
- What the product must do: Where the recorder stops early, the interview carries the best camera sound for the rest rather than going silent, and says so.
- Kind: 3
- From: D02-025

### CFI-012: A recorder covering only an interview's second hour matched nothing.
- What was going on: The recorder started late, so against the first camera file it scored 0.018 and was excluded; against the second camera file it scored 0.877.
- What the product must do: Recorder audio is matched against every camera file of the interview, and a recorder covering only part of it is still placed.
- Kind: 3
- From: C06-004

## Frame rates

### CFI-013: Blackmagic cameras record true 30.000 or 24.000 fps; Sony records 29.97 or 23.976.
- What was going on: The Pyxis records true 24.000 beside an FX3 at 23.976; Resolve retimes a 30.000 clip onto 29.97 by time, so frames sit up to half a frame off.
- What the product must do: Mixed-rate angles are reported on arrival and stay in sync without drift, and a one-frame mismatch from a true-rate file is not called a broken build.
- Kind: 1a
- From: D02-001, M05-054

### CFI-014: Mixed frame rates and misread drop-frame timecode drift a multicam out of sync.
- What was going on: True 30 treated as 29.97 drifts 1.8 frames a minute; 29.97 drop-frame timecode read as non-drop drifts about 50 frames in 25 minutes.
- What the product must do: Every clip's frame rate is handled exactly, drop-frame timecode is decoded as drop-frame, and a mixed-rate shoot states what drift it costs.
- Kind: 1a
- From: C04-055

### CFI-015: An interview's picture drifted from its own sound, in sync at one instant only.
- What was going on: A Blackmagic camera with off-speed on put a 29 fps sensor into a 30p file, so picture ran 3.45% fast; Resolve shows "Camera FPS 29" beside "Shot Frame Rate 30".
- What the product must do: Clips whose sensor rate differs from their file rate are flagged on arrival with the speed correction (about 96.7%), and never synced by their own audio.
- Kind: 1a
- From: P13-011, M01-001, D02-024, P14-008

### CFI-016: New material with no stated frame rate defaults to 29.97 drop-frame.
- What was going on: Every studio interview and timeline measured 29.97 drop-frame, and the owner set it as the default.
- What the product must do: Timelines and clips with no stated rate default to 29.97 drop-frame, and a rate a file states is always kept.
- Kind: 2
- From: M01-058, P10-006

### CFI-017: New cuts silently used coarse timing and 25 fps though word timing existed.
- What was going on: When the word timing could not be reached, a new cut list fell back to subtitle timing and a default rate for all 258 cards, with no warning.
- What the product must do: Any clip whose word timing or frame rate is missing or guessed is named, with a warning, before a cut list is made from it.
- Kind: 3
- From: M01-060, P10-005, L04-032

## Facts about Resolve: rates, multicams, timecode

### CFI-018: Resolve clips keep the frame rate the project had when they were imported.
- What was going on: WAVs imported into a 24 fps project stay 24; positions counted in 29.97 timeline frames put 11 of 16 interviews 0.4 to 25 s out and stretched a timeline 401 s.
- What the product must do: Every position sent to Resolve is computed in that clip's own rate, and each build is read back in seconds and fails loudly beyond one frame.
- Kind: 1a
- From: P12-023, M02-046, D02-017, P11-061

### CFI-019: Resolve refuses a scripted timeline rate, and a new project defaults to 24 fps.
- What was going on: Scripting refuses to set a timeline's own rate, and a project's rate can change only while it holds no timelines.
- What the product must do: Before any timeline is built, the project's rate is checked against the cameras and set while empty, or the build refuses with the reason.
- Kind: 1a
- From: M02-049

### CFI-020: Resolve's scripting has no way to create a multicam clip.
- What was going on: A multicam needs Resolve's "Create New Multicam Clip Using Selected Clips" dialog, which scripting cannot call, so each interview took a manual step or about 46 s of driven clicks.
- What the product must do: Multicam creation never assumes Resolve offers a scripted way, and any step left to a person in Resolve is named exactly.
- Kind: 1a
- From: M02-054

### CFI-021: A two-camera interview came out of Resolve as a multicam with 59 angles.
- What was going on: Resolve's multicam-from-selected-clips makes every FILE an angle, and its scripting cannot build, repair or move items in a multicam.
- What the product must do: A multicam built from cameras that split recordings into many files has exactly one angle per camera.
- Kind: 1a
- From: C04-052

### CFI-022: Resolve's scripting cannot reach multicam angles or set a transcription language.
- What was going on: Scripting exposes no multicam angles, and setting the transcription language returns false for every value, so auto-detect picked English for Mandarin interviews.
- What the product must do: Nothing that prepares footage depends on these calls, and anything Resolve cannot do is done another way or reported, never silently skipped.
- Kind: 1a
- From: P07-055, M04-018

### CFI-023: A Resolve multicam has no media file and no frame rate of its own.
- What was going on: A multicam is a sequence of angles: its rate and start timecode live only in Resolve's record, and its rendered audio has no video to read a rate from.
- What the product must do: A multicam's rate and timecode come from Resolve's own record of it, and its audio-only preview says plainly there is no picture.
- Kind: 1a
- From: D04-021

### CFI-024: Resolve's audio-only render of a one-microphone multicam plays in one ear.
- What was going on: Resolve's Audio Only preset writes a single-input multicam as stereo, sound left and only converter noise right.
- What the product must do: Interview audio with exactly one channel above about -60 dBFS is made true mono before anything uses it; a real second microphone is kept.
- Kind: 1a
- From: C05-082, P11-008

### CFI-025: A multicam's audio render came out 13 minutes long instead of 16.
- What was going on: In and out marks set inside a Resolve multicam limit what it renders, so the export was truncated without warning.
- What the product must do: An audio render of a multicam always covers its full length, with any in and out marks cleared first.
- Kind: 1a
- From: P03-010

### CFI-026: Word times for a plain audio recording landed an hour late.
- What was going on: In Resolve a plain WAV starts at 00:00:00:00 while timelines and multicams start at 01:00:00:00; mixing the two bases left 73 clips with no text.
- What the product must do: Word times are measured from each recording's own start timecode, and two timings of one clip are combined only after checking they share a time base.
- Kind: 1a
- From: P16-037, C06-081, D03-036

## Grouping clips and building the multicam

### CFI-027: A folder can hold someone else's interview, and one recording two interviews.
- What was going on: One person's folder held another's whole interview, a tape held a husband's then his wife's interview, and one interview came in two sessions three hours apart.
- What the product must do: Grouping shows who introduces themselves and when, and a person can move a file to another interviewee, split a recording at a time, or join sessions.
- Kind: 3
- From: D02-008, M02-052

### CFI-028: The same interviewee's name arrives romanised in different orders and spellings.
- What was going on: "Huang Chi-wen" and "Chih-Wen Huang" are one person, while "Taipei Zookeeper" matched "Taipei Zoo Spokesperson" exactly at a 0.50 threshold.
- What the product must do: Grouping by person survives reordered and re-spelt romanisations, and a borderline name match is shown for a person to confirm before anything is filed.
- Kind: 3
- From: D01-050, D06-015

### CFI-029: Interview multicams start at the first question and hold only interview takes.
- What was going on: The owner: "cut them to start when the first question is asked"; bins held b-roll and b-camera takes, once 159 short takes after the recorder stopped.
- What the product must do: One multicam per interviewee, starting at the first question and ending at the earlier of the last interview take and the end of its sound, b-roll left out.
- Kind: 2
- From: P10-033, P12-060, D02-027

### CFI-030: The crew's opening question is often too quiet to hear.
- What was going on: With the question off-mic, the interview start fell on the answer with a 1.5 s lead, and had to be moved earlier by hand to include it.
- What the product must do: An interview's start includes the opening question even when faint, and a person can move the start without rebuilding anything.
- Kind: 3
- From: D02-010

### CFI-031: Switching angle in an interview multicam must never change the sound.
- What was going on: A camera microphone sounds different from the recorder or lav, so sound jumping between them as angles switch is jarring.
- What the product must do: Every angle of an interview multicam carries the same best microphone.
- Kind: 3
- From: P10-035, D01-062

### CFI-032: Angles placed by clock were off by up to a second, take by take.
- What was going on: Camera clocks differ by a constant of minutes, and creation times jitter by a second per take.
- What the product must do: Every take of every angle is synced to sound within a frame, and a take that cannot be matched is moved by the agreed camera offset, not left behind.
- Kind: 3
- From: C04-057

### CFI-033: A camera with no usable sound can only be placed by clock or picture.
- What was going on: Silent angles were placed from that camera's clock error on other shoots (stable at 148-151 s) or by picture motion; clock placement once opened on a long empty stretch.
- What the product must do: Cameras found per session are shown, an angle placed without sound is marked unverified for a person to check, and no multicam opens on an empty stretch.
- Kind: 3
- From: D02-004, P10-034

### CFI-034: A one-camera stop-start event laid out by the clock is mostly empty.
- What was going on: A press conference shot on one camera, laid out by wall clock, opened with 30 s of picture in 80 s of nothing.
- What the product must do: A single camera that stopped between takes can be laid out with its takes back to back in recorded order.
- Kind: 3
- From: D02-026

### CFI-035: Re-syncing a multicam moves the picture, never the edited sound.
- What was going on: All editing is cut against the sound; the owner: "the audio itself must not move an inch... only the video can be moved", with the recorder's live channel as mono.
- What the product must do: A sync repair shifts only picture on every angle, and every audio clip keeps its exact position and in-point, checked before and after.
- Kind: 2
- From: D02-018, P13-004, M02-048, P12-022

### CFI-036: Swapping in better audio must not change an interview's length.
- What was going on: The owner: "sync all the zoom audio into the multicams WITHOUT changing the length", and no re-transcribing "because the audio timing is the same".
- What the product must do: Replacing an interview's sound keeps its length to the frame and every cut span intact, reuses its word timing, levels the new sound, and leaves correct angles untouched.
- Kind: 2
- From: C06-006, P11-060, D01-008

### CFI-037: Better audio shorter than the old left a silent tail under a cut.
- What was going on: One interview's recorder file ended 0.93 s before the furthest cut, so that cut's last second went silent.
- What the product must do: An audio replacement that cannot cover every span the cuts use either fills the tail from the old sound or refuses; it never leaves silence.
- Kind: 3
- State: still open
- From: D01-010

### CFI-038: Each interviewee's multicam wears that interviewee's colour from the plan.
- What was going on: The owner colours each interviewee's cards in the plan and wants their multicam clips in Resolve to carry the same colour from the start.
- What the product must do: Every interviewee's multicam clip shows that interviewee's plan colour in Resolve from the moment it is made.
- Kind: 2
- From: P04-003

### CFI-039: Resolve's "Brown" clip colour is never used; "Chocolate" is the brown.
- What was going on: The owner ruled that the mustard-ochre "Brown" is never assigned to anything; the chocolate brown is fine.
- What the product must do: No colour the product assigns in Resolve or on cards is ever Resolve's "Brown".
- Kind: 2
- From: P07-039
- Move to: cards-to-resolve-and-exports

## Facts about Resolve's own transcription

### CFI-040: Resolve's own transcription leaves holes and garbles specialist words.
- What was going on: It skipped 20 to 50 s stretches of real speech, once 3:55, with no sign, mangled 代孕 as 待遇, and took 44 to 90 s per clip.
- What the product must do: No transcript the editor relies on comes from Resolve's transcription; any Resolve transcript brought in is checked for holes against an independent one.
- Kind: 1a
- From: M02-055, D02-021, P12-018

### CFI-041: Resolve transcribes a multicam to the end only from a 24-bit recorder track.
- What was going on: A 16-minute multicam stopped at 13 minutes and another left a 270 s hole; with a 24-bit recorder render active on track 1, both came back whole, 476 words more.
- What the product must do: When Resolve must transcribe a multicam, it does so against a full 24-bit recorder render, and the result is checked for holes.
- Kind: 1a
- From: P03-011, D06-013

### CFI-042: Resolve's transcription language is one project-wide setting, and redoing returns the cache.
- What was going on: There is no per-clip language (46 of 84 English clips came out as fluent nonsense Mandarin), and re-transcribing returns the cached result unless it is cleared first.
- What the product must do: Anything asking Resolve to transcribe sets each clip's real language, clears the earlier result first, and restores the project setting afterwards.
- Kind: 1a
- From: C04-064, P09-001, G01-052

### CFI-043: "(Speaking In Foreign Language)" in a Resolve transcript means the wrong language.
- What was going on: Mandarin transcribed as English gave 26 minutes of placeholders, 334 words, against 3,661 in Mandarin; "(Blank Audio)", "(Music Playing)" and one token repeating for minutes mean no speech.
- What the product must do: A placeholder-filled transcript is treated as wrong-language and redone, and no cut is placed in a placeholder or repeated-token span.
- Kind: 1a
- From: G01-053, P08-055, D06-014

### CFI-044: Resolve writes Mandarin in Simplified characters and ignores sentence ends.
- What was going on: Resolve emits Simplified while the studio works in Traditional, mishears names and terms, and breaks cues across sentences; byte comparison against Traditional words failed.
- What the product must do: Mandarin text is compared in either script or a mix, and no card's text or boundaries depend on Resolve's transcription.
- Kind: 1a
- From: M03-039, D06-010, D03-037

### CFI-045: Resolve's scripting cannot read back a clip's transcription in full.
- What was going on: The transcription property stops after 10 lines; regenerating subtitles from audio re-transcribes angle 1's camera mic and recovered about 45% of speech, with 130-second holes.
- What the product must do: Transcripts used for cutting carry every word with its time, never a scripted read-back or a regenerated subtitle pass.
- Kind: 1a
- From: D01-048, M05-069, P03-012

### CFI-046: Resolve's transcription sometimes crushes a sentence into one millisecond.
- What was going on: Two of ten clips had 1 ms cues carrying full sentences, cues starting before the last ended, and rates up to 46,000 characters per second; re-transcribing did not fix one.
- What the product must do: Any transcript brought in is swept for tiny cues with real text, backwards starts and absurd rates, and those spots are flagged before a cut uses them.
- Kind: 1a
- From: D06-011

### CFI-047: Resolve refuses to transcribe after a render until the Edit page is opened.
- What was going on: After a Deliver-page render every clip refused transcription; sharing the GPU with another transcriber dropped Resolve to real time and stalled it 20 minutes.
- What the product must do: Any Resolve transcription starts from the Edit page and never runs beside another GPU transcription.
- Kind: 1a
- From: D01-061

### CFI-048: Spans timed from Resolve's subtitle cues run up to six seconds long.
- What was going on: Of 435 spans timed from exported cues, none ran shorter than word timing and 147 ran longer (worst 5.94 s, 23% by over 2 s); Mandarin cues are long.
- What the product must do: Spans timed only from subtitle cues are marked approximate wherever shown or trimmed, and never cut a quote short.
- Kind: 1a
- From: D04-069, C04-079

## Speech-to-text: rulings

### CFI-049: Transcripts and word timing come only from the product's own speech-to-text.
- What was going on: After repeated holes in Resolve's transcripts the owner: "we never want to use resolve", and "jettison the srt and resolve transcripts"; names are fixed by hand instead.
- What the product must do: Text and word timing come from one speech-to-text run per recording; Resolve's transcription is never run, offered or reconciled, and each transcript names what made it.
- Kind: 2
- From: P15-018, M03-040, D02-022, P11-013

### CFI-050: Transcribing clips must never need Resolve open.
- What was going on: The owner: "Why does [the speech-to-text] need Resolve open? It just runs locally on the machine." Touching Resolve's scripting needlessly also risks killing it for the session.
- What the product must do: Transcription and the clip facts it needs work with Resolve closed and never connect to Resolve at all.
- Kind: 2
- From: D04-020

### CFI-051: When paid transcription runs out of credit, transcription carries on locally.
- What was going on: The owner's rule: transcribe with the paid cloud service first, and fall back to a local engine on the studio's GPU when its credit runs out.
- What the product must do: Transcription continues on the local engine when the paid service refuses for lack of credit, and each transcript says which engine made it.
- Kind: 2
- State: fixed, never shipped
- From: M04-085

### CFI-052: Nothing spoken may be missing from a transcript, quiet questions included.
- What was going on: The owner: "It matters HUGELY that nothing be missing"; a silence filter dropped off-mic questions, about 14 minutes on one interview, 0.4 to 8 minutes on others.
- What the product must do: Any stretch over 3 s where speech is audible but no words came back is transcribed again, so the interviewer's quiet questions are kept.
- Kind: 3
- From: P03-009, D02-011

### CFI-053: Language is detected per stretch of speech, never per file or from a name.
- What was going on: The owner: "we should just enable language detection", interviews switch language "so it should be able to cope"; one-language captioning skipped a bilingual film's Chinese.
- What the product must do: Each stretch is transcribed in the language spoken there, the line at each switch is kept, and no language is chosen from a person's name.
- Kind: 2
- From: M02-066, L05-062, M05-041, P01-040

### CFI-054: Forcing Mandarin on a mixed batch turned English interviews into Chinese.
- What was going on: An English speaker with a Chinese name was batched as Mandarin; forced speech-to-text silently translated her into Chinese at full confidence, then cards translated it back.
- What the product must do: No language is forced across a batch, a forced run's confidence is never trusted, and each transcript's language is checked before anything is built from it.
- Kind: 3
- From: M01-059

### CFI-055: Crew asides inside a long run of the other language must not split it.
- What was going on: Short crew remarks like "Thank you." or "Cut." sit inside long Mandarin runs and would start false language stretches.
- What the product must do: A stretch under 3 s in a language neither neighbour speaks is absorbed into its neighbours.
- Kind: 3
- From: C05-060

### CFI-056: A misdetected language makes the speech-to-text invent text in random languages.
- What was going on: An English interview came out as a jumble of other languages, and forcing one language on a multilingual speaker turns the others into fluent nonsense.
- What the product must do: An editor can set an interview's language and re-transcribe it, and each transcript shows which language it was made in.
- Kind: 3
- From: P12-042

### CFI-057: Each speaker is transcribed in their own language, and an interpreter can be left out.
- What was going on: One student spoke Vietnamese through an interpreter; the owner: "I only want her bits, I don't want the translation".
- What the product must do: Each speaker's speech is transcribed in its own language, and an interviewee's own words can be kept while an interpreter's lines are dropped.
- Kind: 2
- From: P14-009

### CFI-058: Every transcribed clip has per-word timing, older ones included.
- What was going on: The owner: "how is there no word level timings it makes no sense"; an episode transcribed earlier had none, and two clips side by side differed.
- What the product must do: Every interview has word timing by default, older interviews lacking it are filled in on their own, and a clip without it says why.
- Kind: 2
- From: P15-046, P11-067

## Speech-to-text: facts and situations

### CFI-059: Speech-to-text word times do not mark where a word starts in the audio.
- What was going on: Over two interviews a word's start time sat a median 88 ms from the nearest dip in the audio, against 74 ms for a random moment.
- What the product must do: No transcribed word time is treated as a frame-accurate cut point; anything needing one measures the audio itself.
- Kind: 1a
- From: C06-042, P11-064

### CFI-060: Mandarin timed words arrive one character at a time.
- What was going on: Speech-to-text splits Mandarin by sound, so names like 林保署 and words like 颱風 arrive as separate characters.
- What the product must do: Anything working on timed Mandarin words regroups characters into real words first, never assuming one timed word is one dictionary word.
- Kind: 1a
- From: D07-005, P15-030

### CFI-061: Mandarin speech-to-text writes soundalike characters, hiding search terms.
- What was going on: A search for a key term found nothing because the transcription wrote 放 as 犯 or 繁 throughout; the term existed only in the question sheet.
- What the product must do: Transcript search finds soundalike spellings of a Mandarin term, so a misheard word never hides the passage.
- Kind: 1a
- State: still open
- From: P16-040

### CFI-062: A batch transcription silently skipped 16 of 51 clips.
- What was going on: A first pass over 51 downloaded clips left 16 without a transcript and reported nothing; a re-run picked them up.
- What the product must do: After a batch, every clip is checked for a transcript, and each missing one is retried or listed.
- Kind: 3
- State: outcome not found
- From: M04-040

### CFI-063: Re-running transcription over a finished folder should cost seconds, even after copying.
- What was going on: Folders are re-run often, and the same file copied to another disk is the same clip; transcribing it again wastes minutes per hour of audio.
- What the product must do: A re-run skips every clip already transcribed, including the same file copied elsewhere, and finishes in seconds.
- Kind: 3
- From: D04-003

### CFI-064: A wrong speaker label on narration is worse than no label.
- What was going on: Over a narrator with archive audio a second voice was heard but owned no word, while a news studio clip rightly got four speakers.
- What the product must do: A word gets a speaker only where that voice clearly owns it, within half a second; otherwise it stays unlabelled.
- Kind: 3
- From: D04-007

### CFI-065: A failure in speaker detection must cost only the speaker labels.
- What was going on: A missing licence, download or undecodable file in speaker detection would otherwise throw away a transcription that had already succeeded.
- What the product must do: When speaker detection fails, the transcript is still written without speakers, and the reason is recorded and shown.
- Kind: 3
- From: D04-006

### CFI-066: Short cuts showed words not in the edit, and audible words greyed out.
- What was going on: Word timing was inexact, so tightly cut cards carried extra words, and greyed-out words were usually the last ones actually heard.
- What the product must do: A card shows exactly the words audible within its cut, with none heard greyed and none unheard shown.
- Kind: 3
- State: outcome not found
- From: P07-046

### CFI-067: Counting seconds of gap overstated missing speech a hundredfold.
- What was going on: Across ten multicams (6h04m), reference cues over transcript gaps suggested 9m40s missing; most gaps were silence or room chatter, and about 40 characters were really lost.
- What the product must do: A missing-speech check measures missing text (is the reference text anywhere within about 90 s), never seconds of overlap.
- Kind: 3
- From: D06-008

### CFI-068: Comparing a transcript's end with the clip's length only finds cut-off endings.
- What was going on: That check flagged a clip 11 s short that was only room tone, and passed every clip whose damage was in the middle.
- What the product must do: A transcript health check looks for holes and bad timings throughout the clip, and an end-time check is labelled a tail check only.
- Kind: 3
- From: D06-012

## Chinese script

### CFI-069: Mandarin text reads as Taiwan writes it, in Traditional characters with 台.
- What was going on: The owner: "we want 滑鼠/影片"; the house style is Taiwan phrasing and 台灣 with 台, while speech-to-text emits Simplified and standard conversion turns 台 into 臺.
- What the product must do: Every Mandarin transcript, word, cue and card is Traditional with Taiwan phrasing and 台, identically in search; text in another language is never converted.
- Kind: 2
- From: C05-003, D07-006, G01-069, P08-052, D04-011

### CFI-070: A transcript and its timed words must be spelled identically.
- What was going on: Script conversion depends on surrounding words; converted per word it gave 類型 where the sentence gave 型別, 364 divergences across 13 of 16 transcripts.
- What the product must do: Script conversion runs over whole sentences and is mapped back onto the words, so text and timed words match character for character.
- Kind: 3
- From: D07-003, D03-003

### CFI-071: English words from separate timed pieces were glued together as "readyfor".
- What was going on: Joining timed pieces with nothing between them suits Chinese but glued English words across the joins.
- What the product must do: Timed pieces are joined with a space unless the join falls between Chinese or Japanese characters.
- Kind: 3
- From: D05-023

## The transcript and its English

### CFI-072: A transcript, its translation, word times and word links are one file.
- What was going on: The owner: "make it one file where everything is together", with a readable copy any clip's transcript can be opened and browsed from.
- What the product must do: Correcting a word never detaches its timing or English, a readable Markdown copy is always kept in step, and old transcripts import keeping every paragraph reference.
- Kind: 2
- State: still open
- From: P19-021, P08-045

### CFI-073: Each interviewee has exactly one transcript.
- What was going on: A re-paragraphed copy saved beside the original doubled the English on every card; the owner: "just delete the original and make this the new single transcript".
- What the product must do: Each interview has exactly one transcript, reworking its paragraphs updates that one in place, and a second copy is flagged, never merged in.
- Kind: 2
- From: M03-066, P15-011

### CFI-074: A transcript reads as meaning-based paragraphs with questions marked and full English.
- What was going on: The owner wants paragraphs by meaning, the interviewer's question as a heading, each paragraph translated "NATURALLY and COMPLETELY", and a reference per paragraph.
- What the product must do: Each paragraph carries the question it answers, its verbatim original, its full natural English, and a reference that survives edits and renames.
- Kind: 2
- From: P01-005, M05-022

### CFI-075: A card holds at least two sentences, never a single word or sentence.
- What was going on: The owner had a speaker's transcript re-paragraphed so that no card held a single sentence or word.
- What the product must do: Transcripts split into cards of at least two sentences, merging shorter fragments into a neighbour and keeping the first one's reference.
- Kind: 2
- From: M04-030

### CFI-076: Bilingual transcripts show the English line above the Chinese.
- What was going on: The owner asked for every Chinese transcript, news reports included, translated "so I can see them english above the chinese".
- What the product must do: Every bilingual block shows English above its Chinese, and adding English never moves a paragraph reference a cut already uses.
- Kind: 2
- From: M03-051, P09-031

### CFI-077: Every interview yields a complete original text and a complete English text.
- What was going on: The owner asked for "a full ZH subtitle and a full EN subtitle", with likely mishearings flagged using a list of names and terms he supplies.
- What the product must do: Every interview has a complete original and English text, and likely mishearings are flagged against the owner's list of names and terms.
- Kind: 2
- From: P01-004

### CFI-078: Adding the English must never correct the transcribed words.
- What was going on: The owner ruled that no speech-recognition corrections happen in the translation pass, "now and going forward".
- What the product must do: Translating leaves every transcribed word exactly as it was; any change to the words is a separate step a person chooses.
- Kind: 2
- From: P04-065

### CFI-079: Speech in any language other than English gets English.
- What was going on: Italian, French and German cards got no English, and Vietnamese and Indonesian read as English, because only Chinese counted as foreign; the owner: "add translating from any detected language".
- What the product must do: Any non-English language is detected and translated, and real English is never sent for translation and shows its words once.
- Kind: 2
- From: C06-054, P13-016

### CFI-080: A card's English came from a passage further down the interview.
- What was going on: Given neighbouring paragraphs as context, the translator copied their English out in order, landing a paragraph or more ahead (once 35 s) while the Mandarin was right.
- What the product must do: A cut's English is the translation of exactly the words it plays; English copied from outside its time span (60 or more characters) is refused.
- Kind: 3
- From: M01-023, C06-024, P11-025, L10-024, L08-042

### CFI-081: Staged cards must show English like cut cards do.
- What was going on: The owner: "the staged section shows English translations too".
- What the product must do: Every card, staged or cut, shows the English for its words.
- Kind: 2
- From: P11-055

### CFI-082: Throttled translation looked stuck, with no sign why.
- What was going on: Hundreds of Mandarin cards waited in the translation service's "too many requests" back-off with nothing on screen, and results appeared only after the next edit.
- What the product must do: When translation is throttled or failing the screen says so, and each finished translation appears as soon as it lands.
- Kind: 3
- From: C05-041, P09-028, M03-054

### CFI-083: Two computers overwrote each other's translations.
- What was going on: Each program read the shared translations once at start and saved its whole copy over them.
- What the product must do: A translation made on any computer appears on every other, and a save never removes another computer's entries.
- Kind: 3
- From: G01-062

## Word links between the original and the English

### CFI-084: A name or compound must light its whole English as one unit.
- What was going on: The owner: "the compound splitting would be an issue": 林保署 linked Forestry to 林 and Agency to 保署, and 莫拉克颱風 had Typhoon and Morakot swapped.
- What the product must do: A multi-character name, compound or abbreviation links as one unit with one gloss, any of its characters lights all its English, and no boundary falls inside it.
- Kind: 2
- From: D07-026, P15-029, C06-079

### CFI-085: One stray word link must not throw away the whole paragraph's links.
- What was going on: A compound can straddle a phrase edge, so a link pointing outside its phrase is normal, yet it failed the whole paragraph.
- What the product must do: An invalid link is dropped on its own and the paragraph's other links are kept.
- Kind: 3
- From: D07-027

### CFI-086: Paragraphs whose word links failed were never asked again.
- What was going on: Failures were stored as final, so re-runs skipped them; of 1,605 paragraphs 15 failed, a retry fixed 10, and 5 failed because their English was a summary.
- What the product must do: Failed paragraphs are retried on the next run, and any that fail twice are shown with a plain reason such as "English is a summary, not a translation".
- Kind: 3
- State: outcome not found
- From: P15-034, P17-032

### CFI-087: A long background run threw away most of its paid answers at a cut-off.
- What was going on: 392 of about 500 word-link calls ran past a 180-second limit and were discarded after being paid for; with room to finish, 600 paragraphs took about 20 minutes.
- What the product must do: A background batch gives each call room to finish, and an answer already paid for is never discarded for being slow.
- Kind: 3
- From: P15-033

### CFI-088: Word-link accuracy is measured before any other linker or offline option is used.
- What was going on: The owner asked about offline models, then "dont build it for offline yet"; first test "the accuracy of word links on a word aligner vs [the assistant]".
- What the product must do: Word-link quality is scored against a hand-checked answer key, and any dedicated aligner or offline option is compared on the same paragraphs before it ships.
- Kind: 2
- State: still open
- From: P15-035, D07-030

## Running on its own, with a hand on every decision

### CFI-089: Everything from clips to word links runs on its own.
- What was going on: The owner: "make the word link pass part of the multicam pipeline ... so that all of this gets done automatically at the end".
- What the product must do: Once clips are in, grouping, sync, multicam, transcript, English and word links all complete with no step started by hand.
- Kind: 2
- From: C06-078

### CFI-090: Every automatic guess in footage processing can be corrected by hand.
- What was going on: The owner: "yes automatic guess can be corrected": a word, a translation, a speaker, an interview grouping.
- What the product must do: Each automatic decision is visible and settable by hand, and a later automatic pass never overwrites a value a person set.
- Kind: 2
- From: P19-022

### CFI-091: A long processing step ran ten minutes with nothing on screen.
- What was going on: Sorting showed no progress for ten minutes, and the owner asked to see transcription progress too.
- What the product must do: Every processing step that takes more than a few seconds shows live progress per interview.
- Kind: 2
- From: P03-014

### CFI-092: Clips with no transcript are flagged and can be transcribed from the editor.
- What was going on: The owner: "flag it, show progress, one trigger", for one clip, every clip, or "clips ACTUALLY USED in the live cut file", on a chosen computer.
- What the product must do: Untranscribed clips are marked; a person can transcribe one, all, or the open cut's, on a computer picked from a list defaulting to the last, with live progress.
- Kind: 2
- From: C05-040, P09-025, L04-021

### CFI-093: Re-transcription must never overwrite a hand-edited transcript or touch the footage.
- What was going on: Source footage folders are read-only, and a transcript a person corrected is worth more than a fresh machine pass over the same clip.
- What the product must do: Transcription never writes into source footage folders and never overwrites a hand-corrected transcript unless a person explicitly forces it.
- Kind: 3
- From: D04-002, C04-077

### CFI-094: Re-preparing or renaming an interview must not orphan its cuts or translations.
- What was going on: Cuts and paid translations pointed at the existing paragraphs; respelling 398 words would have orphaned 105 translations, and renaming broke the tie between transcript and clip.
- What the product must do: Re-transcribing, re-paragraphing, respelling or renaming an interview keeps every existing cut's reference and every translation attached, with no new translation paid for.
- Kind: 3
- From: M02-065, D02-028, D07-010, D06-016

### CFI-095: A corrected transcript left the old words on cuts already made.
- What was going on: Each cut's words were stored with the cut and refreshed only when trimmed, and changed transcripts were read only at a restart.
- What the product must do: A transcript added or changed shows on every card and saved cut within minutes, with no restart and no edit.
- Kind: 3
- State: outcome not found
- From: P10-028, L05-063, C05-061, P15-013

### CFI-096: A second speech-to-text pass rewrote clip words, so their English vanished.
- What was going on: Re-timing interviews with a fresh transcription brought different characters and words (他 heard as 它), and re-cutting 707 clips from it broke their English.
- What the product must do: New word timings only move a clip's edges; its words stay in the transcript's own wording and characters.
- Kind: 3
- From: P16-019

### CFI-097: Changing how spans are worked out must not silently move cuts already placed.
- What was going on: Every span in every hand-ordered cut rests on the current rule; a different rule would move cut points across every project unseen.
- What the product must do: A change in how spans are computed alters no placed cut's start or end unless the editor is shown each change and accepts it.
- Kind: 3
- From: D07-008

### CFI-098: An interview reused from another episode had no timing and no audio.
- What was going on: An excerpt transcript points at another episode's recording, and its audio only ever lived in that episode's folder; 26 cards came out unmatched.
- What the product must do: An excerpt reused in another episode times, plays and draws its waveform from its declared source; a pointer that loops or leads nowhere is reported.
- Kind: 3
- From: P10-061, C05-075, P11-005, D05-041

### CFI-099: The editor found no transcripts in an episode's folder.
- What was going on: Pointed at one episode's folder, the editor read no transcripts at all, with no reason given.
- What the product must do: Opening an episode lists every transcript in it, or says which files it rejected and why.
- Kind: 3
- State: outcome not found
- From: P07-059

## Footage files and files made from them

### CFI-100: A file dropped on a web page gives its name and bytes, never its path.
- What was going on: Browsers hand a dropped file's name, size and contents to the page but not its place on disk, and uploading multi-gigabyte video through a page is impractical.
- What the product must do: Dropped media is found on the NAS by name and size; if it is not there, the person is told to put it there and drop it again.
- Kind: 1a
- From: D05-071

### CFI-101: A NAS share limits a file name to 255 bytes, not characters.
- What was going on: A Chinese character is 3 bytes, so a 244-byte news title plus a working suffix hit 256 and the audio was never made, though its waveform showed.
- What the product must do: Every name made from a title or source name fits 255 UTF-8 bytes, cut on a character boundary keeping the start, a hash and the id.
- Kind: 1a
- From: C05-009, D04-015, G01-072, C06-056, M01-018, P13-013

### CFI-102: Windows refuses command lines longer than about 32,000 characters.
- What was going on: A folder of news clips with long CJK titles exceeded the 32,767-character limit (error 206) before any work began.
- What the product must do: Processing any number of long-named files on Windows never fails on command-line length, and partial batch results survive a crash.
- Kind: 1a
- From: D04-014, C05-010, G01-073

### CFI-103: A made file newer than its source can still be out of date.
- What was going on: A waveform made at an old rate was newer than its source, so "newer means done" kept the stale file forever.
- What the product must do: Whether a made file is current is judged by its content or format, not by its date alone.
- Kind: 3
- From: C03-027

### CFI-104: Most interviews had no small listening copy or waveform ready.
- What was going on: These were made only when a page asked, so a new project had them for just 2 interviews, and working offline offered 2.9 GB of full WAVs.
- What the product must do: Every clip's small listening copy and waveform are made as soon as its sound is final, before anyone opens the editor.
- Kind: 3
- From: P11-069, C06-058

### CFI-105: Drawing a waveform held a whole decoded clip in memory.
- What was going on: Long interview clips decode to gigabytes of audio, and every waveform job kept the whole decode in memory at once.
- What the product must do: Waveforms for clips of any length are made in bounded memory, and several at once cannot exhaust the machine.
- Kind: 3
- State: fixed, never shipped
- From: L11-074

## Bringing the studio's existing transcripts in once

### CFI-106: Existing transcript paragraphs went dead when timed from a second transcription.
- What was going on: A second transcription of the same audio differs by a character or two per paragraph; 80 to 90% got no timing, and a one-character-off 31-character paragraph scored 0.732.
- What the product must do: On import, every paragraph of any length, hand-corrected ones included, gets timing even when its words differ slightly from the timed words, with honest confidence.
- Kind: 3
- From: P11-012, C05-083, P11-053, D07-007

### CFI-107: An imported paragraph that cannot be placed says only "text not found".
- What was going on: Two transcriptions of one interview disagreed on about 40% of paragraphs (309 cards unmatched), and diagnosing six unmatched cards took a long hunt.
- What the product must do: An imported paragraph that cannot be placed is kept, listed, and shows the closest stretch of the recording and how similar it was.
- Kind: 3
- State: still open
- From: D07-009, D04-023

### CFI-108: An existing Resolve transcript export had holes of 20 to 30 seconds.
- What was going on: One interviewee's export missed long stretches, so only 1 of his 155 paragraphs could be placed against it.
- What the product must do: On import, when one word source cannot place a transcript every other source for that clip is tried; an unplaced interview stays listed as "transcript not linked".
- Kind: 3
- From: C06-046, P12-017

### CFI-109: Matching clips by fuzzy name landed interviews on the wrong footage.
- What was going on: Across 6,198 library clips, loose name matching put interviews on YouTube rushes and a music file, and folded news packages sharing a long name prefix into one.
- What the product must do: On import, each transcript is tied to its clip by an explicit pointer or exact name within the episode, and an unknown or ambiguous one is reported.
- Kind: 3
- From: D04-022, M01-071, C04-078

## Montages

### CFI-110: A montage uses only downloaded material, never the studio's own interviews.
- What was going on: The owner's rule: a montage is news, coverage or archive the product downloaded, with credits, never the studio's interview material.
- What the product must do: Building a montage refuses interview footage and any clip without a credit record.
- Kind: 2
- From: C06-048
- Move to: cards-editor

## Sealed

### CFI-S01: Forced to one language, the speech-to-text translates or invents fluent nonsense.
- What was going on: Forced to Mandarin it silently translated English speech at full confidence; forced to Chinese it rendered Vietnamese and Indonesian as plausible Chinese, and its last cue runs on over silence.
- What the product must do: The language is never forced on unknown speech, a forced run's confidence is never trusted, and a cue's end is trimmed to where speech stops.
- Kind: 1b
- Tool: Whisper (faster-whisper large-v3, forced language)
- From: C05-059, L05-060, P10-026, M03-043

### CFI-S02: The speech-to-text's own language detection guesses once or translates mid-file.
- What was going on: It picks one language from the first 30 s, often crew talk; its per-30-second multilingual mode rendered a whole Mandarin middle in English, and crew words form false islands.
- What the product must do: Language is decided per stretch of speech outside its built-in modes, with islands under 3 s absorbed, and test files come back at the true boundaries.
- Kind: 1b
- Tool: faster-whisper 1.2.1 (language detection and multilingual mode)
- From: L05-061, P10-027, M02-067

### CFI-S03: The speech-to-text dropped the middle of long spans and ran past the end.
- What was going on: Long spans lost their middle, and forced English invented about 25 seconds past the audio's real end.
- What the product must do: Mixed-language passes run in short windows of about 12 seconds, and nothing timed past the audio's real end is kept.
- Kind: 1b
- Tool: faster-whisper large-v3-turbo
- From: M05-042

### CFI-S04: The speech-to-text's voice filter removed an interviewer's quiet questions.
- What was going on: Its voice-activity filter drops quiet speech; on one interview almost every off-mic question vanished, 14 minutes of them.
- What the product must do: Stretches with sound but no words are re-run without the filter, and invented filler from that run is rejected.
- Kind: 1b
- Tool: faster-whisper (VAD filter)
- From: M03-042

### CFI-S05: Re-transcribing quiet stretches invents subtitle credits and repeats.
- What was going on: Run on quiet audio without its speech filter, it produced phantom lines such as subtitle-site credits and verbatim repeats of earlier lines.
- What the product must do: Lines recovered from quiet stretches are checked for known phantom phrases and exact repeats and dropped before they reach a transcript.
- Kind: 1b
- Tool: Whisper
- From: D02-012

### CFI-S06: The speech-to-text stamps a few words across long silences and invents words.
- What was going on: Six characters were stamped across 72 s; near-silence returned 22 zero-length mixed-language "words"; a short extracted span hallucinates more than the full file.
- What the product must do: Timing across silence is never trusted, zero-length words are discarded, and transcription runs on whole files, not short excerpts.
- Kind: 1b
- Tool: faster-whisper
- From: D06-009

### CFI-S07: The same clip transcribed twice gives a different number of words.
- What was going on: Plain sequential transcription is not deterministic: one studio clip gave 999 words in one run and 965 in another, a 3.4% spread.
- What the product must do: Checks comparing transcripts tolerate a few percent of run-to-run difference instead of calling it a regression.
- Kind: 1b
- Tool: faster-whisper
- From: D04-010

### CFI-S08: Mandarin words come one character each, with punctuation only in sentence segments.
- What was going on: Joined word by word, Mandarin reads as one unbroken string; sentence boundaries exist only in the sentence-level segments, which cost about a sixth of the output.
- What the product must do: Sentence-level text is kept beside word timing; readable text and paragraphs come from sentences, spans from words.
- Kind: 1b
- Tool: faster-whisper (Mandarin word timestamps)
- From: D04-004

### CFI-S09: Batched transcription was three times faster and silently lost a fifth of a piece.
- What was going on: Batched mode ran 2.9x faster (94x against 32x realtime) but lost 5.1% of words overall, 21.7% on a studio piece with music, and merged 100 segments into 14.
- What the product must do: A speed-up is accepted only if per-clip word counts stay within 1% and timings within 0.10 s at p95; anything that loses words is opt-in.
- Kind: 1b
- Tool: faster-whisper BatchedInferencePipeline
- From: C04-085, P08-053, G01-071, D04-009

### CFI-S10: Transcription crawled and hung while Resolve made proxies on the same GPU.
- What was going on: Sharing the GPU with Blackmagic Proxy Generator, half-precision transcription ran at real time and hung; 8-bit mixed precision ran eight times faster.
- What the product must do: Transcription keeps several times real time on a shared GPU by choosing a lighter precision, or says plainly that it is waiting.
- Kind: 1b
- Tool: faster-whisper (CTranslate2 compute type float16 versus int8_float16)
- From: D02-013, M02-056

### CFI-S11: An hour of rushes transcribes in about three minutes on the studio GPU.
- What was going on: On an RTX 3080: 20 to 24x realtime transcribing, about 20x for speakers, about 10x for both; models load in 2.2 s and 5.1 s.
- What the product must do: An hour of footage transcribes in minutes, and models load once per batch, never once per clip.
- Kind: 1b
- Tool: faster-whisper large-v3-turbo float16 on CUDA, with pyannote for speakers
- From: D04-008

### CFI-S12: A converted speech model silently transcribed with the wrong vocabulary.
- What was going on: A converted model missing its vocabulary file fell back to a small default vocabulary with no error; the correct size was 51,865.
- What the product must do: Loading a speech model checks its vocabulary matches the model and refuses to transcribe when it does not.
- Kind: 1b
- Tool: faster-whisper with CTranslate2 model conversion
- From: M05-003

### CFI-S13: Singing and chanting come out as gaps with no text.
- What was going on: Singing, chanting and an announcer's call left caption gaps, so they could only be found by ear.
- What the product must do: Long stretches of sound with no text are marked, so the editor can find sung or chanted material.
- Kind: 1b
- Tool: Whisper
- State: still open
- From: M04-041

### CFI-S14: Taiwanese Hokkien needs its own model, which writes rough Mandarin characters.
- What was going on: The standard model has no Hokkien; a fine-tune writes Han characters at about 11 times real time, strips all punctuation and gets about 30% of characters wrong.
- What the product must do: Hokkien interviews use a model chosen per interview, their transcripts are marked first drafts, and punctuation is restored before splitting or translating.
- Kind: 1b
- Tool: Breeze-ASR (Whisper fine-tune for Taiwanese)
- From: P03-047, M05-002

### CFI-S15: The speaker-detection models are gated, read only some audio formats, and break on upgrades.
- What was going on: Models load only for an account that accepted their terms, else nothing returns with no error; MP4 fails; newer torch refuses old checkpoints.
- What the product must do: Speaker detection gets decoded 16 kHz mono audio, pinned runtime versions, and an up-front licence check naming which terms to accept.
- Kind: 1b
- Tool: pyannote.audio 3.3 speaker-diarization-3.1 under torch 2.6
- From: D04-005, C04-086, G01-068

### CFI-S16: The cloud speech-to-text writes Mandarin in Simplified characters.
- What was going on: Its Mandarin output is Simplified, so comparing it with the studio's Traditional text fails without conversion.
- What the product must do: Its transcripts are converted to Traditional before they are compared or shown.
- Kind: 1b
- Tool: Soniox
- From: M04-084

### CFI-S17: Every Simplified-to-Traditional conversion table turns 台 into 臺.
- What was going on: The mapping sits in the base table every mode starts from, so even the Taiwan modes rewrite 台灣 as 臺灣, on already-Traditional text too.
- What the product must do: After conversion 臺 is put back to 台 in words, sentences and transcripts alike, and the conversion applied is recorded.
- Kind: 1b
- Tool: OpenCC (s2t, s2tw, s2twp)
- From: D04-012, C04-088, G01-070

### CFI-S18: The Taiwan phrasing rules fire only on whole phrases.
- What was going on: 類型 becomes 型別 and 數據 becomes 資料 as words, but 類 and 型 sent separately come back unchanged, so per-word conversion broke 398 words.
- What the product must do: Conversion runs over the joined text and is split back onto the timed words, never one word at a time.
- Kind: 1b
- Tool: OpenCC s2twp phrase conversion
- From: M04-044, P11-054, D07-004, C06-007

### CFI-S19: Ready-made Chinese word splitters break exactly the names that matter.
- What was going on: One splitter gave 放生 | 態相機 and 颱 | 風; the other's Traditional model gave 林 | 保署.
- What the product must do: Any word grouping is checked on the studio's Traditional Chinese interviews, names and abbreviations included, before it is trusted.
- Kind: 1b
- Tool: jieba and Stanza zh-hant word segmentation
- From: P15-031, D07-029

### CFI-S20: Given an approved translation as context, the model copies it instead of translating.
- What was going on: Asked to translate adjacent cuts with the paragraph's approved English as context, it returned that English verbatim, dealt out across the cuts in order.
- What the product must do: Context given to the translator is limited to each cut's own time slice, and answers matching context verbatim outside it are rejected.
- Kind: 1b
- Tool: Claude Haiku as the caption translator
- From: P11-026

### CFI-S21: A small local translation model copied Chinese straight into the English line.
- What was going on: It passed Chinese runs through, most often reporter sign-offs, personal names and channel brands.
- What the product must do: An English line never contains Chinese characters; one that does is redone, and a block that still fails stays Chinese only.
- Kind: 1b
- Tool: a 7B local model run through Ollama
- From: C05-042

### CFI-S22: The free web translator blocked the studio after about 160 rapid calls.
- What was going on: Calls 0.35 s apart were blocked after roughly 160, and translation silently stopped working.
- What the product must do: Bulk translation spaces its calls so a full episode never gets the studio blocked, and a block is reported instead of returning blanks.
- Kind: 1b
- Tool: Google Translate free web endpoint
- From: P07-064

### CFI-S23: The cheaper assistant model links words as well as the dearer one.
- What was going on: On 20 paragraphs both gave 20 of 20 valid answers; the larger merged phrases like "these black bears" and cost about twice as much per episode.
- What the product must do: Word links run on the cheapest model that passes the answer check, chosen by measured cost and a Chinese reader's judgement.
- Kind: 1b
- Tool: Claude Haiku 5.5 versus Sonnet 5.5
- From: D07-028, P15-032

### CFI-S24: Linking a long paragraph can take minutes and arrive reordered.
- What was going on: Long paragraphs took minutes and 392 calls timed out at 180 s; phrases came back in Mandarin order around English asides.
- What the product must do: Linking allows minutes per call, retries unanswered calls, and accepts phrases listed out of order as long as none overlap.
- Kind: 1b
- Tool: Claude Haiku 5.5
- From: C06-080

### CFI-S25: Resolve stores each clip's transcription as a compressed list of timed words.
- What was going on: Each media-pool item holds its words with start and end seconds, pause markers, paragraph breaks and a language, offset by start timecode as nominal seconds (01:00:00:00 is 3600).
- What the product must do: Read this way, Resolve's text is reproduced exactly (7 of 7 references), times are nominal seconds never converted through timecode, and cue breaks need not match.
- Kind: 1b
- Tool: reading Resolve's project library directly (zstd protobuf per media-pool item)
- From: M05-070, P03-013, D01-049

### CFI-S26: Transcriptions with speaker detection or a zero start were lost from the export.
- What was going on: With speaker detection on, a speaker table precedes the words (15 of 98 clips lost); a word at 0.0 omits its start; "no speaker" is 2^64-1 or 2^64-2.
- What the product must do: Records are recognised by their word entries wherever placed (as few as 3), missing times read as 0.0, and the language field accepted only when it looks like one.
- Kind: 1b
- Tool: reading Resolve's project library directly
- From: G01-055, C04-063, P08-014, M03-041, G01-054

### CFI-S27: Resolve 20 changed its stored transcript layout and every transcript read as missing.
- What was going on: Resolve 20 put an extra length field in front of the stored data, so a reader expecting the older shape returned nothing.
- What the product must do: Every layout seen so far is read, and an unreadable transcript is reported by clip as unreadable, never treated as absent.
- Kind: 1b
- Tool: reading Resolve's project library directly
- From: D05-015, M04-008

### CFI-S28: Writing corrected transcripts back into Resolve's library was never proven.
- What was going on: The stored transcript round-trips byte for byte, but whether Resolve reads a rewritten one was never verified.
- What the product must do: No transcript is written into Resolve's library until a sandbox test shows Resolve reading it back correctly.
- Kind: 1b
- Tool: writing Resolve's project library directly (46-byte header with two length fields, then a zstd frame)
- State: still open
- From: D06-017

### CFI-S29: With a disk-stored Resolve library, every transcript came back empty.
- What was going on: The database library refuses by default a connection used on another thread than the one that opened it, and the failure was swallowed.
- What the product must do: Network and disk Resolve libraries are tested end to end, and a read failing every time is shown as an error, never as empty transcripts.
- Kind: 1b
- Tool: reading Resolve's disk project database with Python's sqlite3
- From: C05-011, G01-074

### CFI-S30: An encoder picks its output format from the file name's extension.
- What was going on: A temporary name with an unknown extension fails or writes the wrong format.
- What the product must do: Every temporary output names its format explicitly, so the finished file is identical whatever it was called while being written.
- Kind: 1b
- Tool: ffmpeg (muxer chosen from output extension)
- From: C03-028

### CFI-S31: Camera microphones agree on loudness contours, not on raw waveforms.
- What was going on: Raw waveforms disagree between mics while loudness envelopes agree; a narrow search found 3 of 43 takes until a whole-track pass found the 154 s offset.
- What the product must do: The coarse offset is found over whole tracks first, then each take in a narrow window, judged against the consensus of strong matches.
- Kind: 1b
- Tool: loudness-envelope cross-correlation for multicam sync
- From: C04-058

## Removed

- P09-023 | superseded by CFI-049
- C05-044 | superseded by CFI-049
- D03-001 | superseded by CFI-049
- D04-018 | superseded by CFI-049
- P06-002 | superseded by CFI-049
- C04-087 | superseded by CFI-069
- M04-046 | superseded by CFI-006
- P06-001 | no longer applies: interviews are cut from the product's own transcripts, not by searching Resolve's
- P03-015 | no longer applies: hand-run stages are gone; footage processing runs on its own
- D05-042 | no longer applies: the notes program's canvas and its links are gone
- P08-048 | no longer applies: the notes program's folder layout is gone
- P04-064 | no longer applies: a transcript is tied to its recording directly, not found by name
- M05-026 | no longer applies: transcripts are no longer found by matching text
- D03-035 | no longer applies: transcripts are no longer found by matching text
- P09-024 | no longer applies: transcripts stored beside a canvas are gone; one transcript file per recording
- P04-053 | no longer applies: the translate button and editor draft translations are gone
- P07-060 | no longer applies: the translate button and editor draft translations are gone
- P13-017 | no longer applies: the translate button and editor draft translations are gone
- P07-054 | no longer applies: the translate button is gone; translation happens once per transcript

