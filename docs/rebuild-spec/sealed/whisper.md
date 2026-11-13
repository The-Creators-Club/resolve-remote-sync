# Sealed notes: whisper

SEALED. Not part of the pack. Released to the rebuild only after its own committed design names this tool. 15 notes.

### BRO-S12: Silent dashcam footage got an invented subtitle-credit line as its transcript.
- Why: The speech-to-text invents text over silence, and quality floors tuned for English reject real Chinese, which is denser.
- Must: Transcripts showing repetition, credit artefacts or implausible density are discarded, with thresholds that accept normal Chinese speech.
- Tool: Whisper speech-to-text
- Where it bit: The b-roll archive

### CFI-S01: Forced to one language, the speech-to-text translates or invents fluent nonsense.
- Why: Forced to Mandarin it silently translated English speech at full confidence; forced to Chinese it rendered Vietnamese and Indonesian as plausible Chinese, and its last cue runs on over silence.
- Must: The language is never forced on unknown speech, a forced run's confidence is never trusted, and a cue's end is trimmed to where speech stops.
- Tool: Whisper (faster-whisper large-v3, forced language)
- Where it bit: Timeline Cards: footage in, ready to cut

### CFI-S02: The speech-to-text's own language detection guesses once or translates mid-file.
- Why: It picks one language from the first 30 s, often crew talk; its per-30-second multilingual mode rendered a whole Mandarin middle in English, and crew words form false islands.
- Must: Language is decided per stretch of speech outside its built-in modes, with islands under 3 s absorbed, and test files come back at the true boundaries.
- Tool: faster-whisper 1.2.1 (language detection and multilingual mode)
- Where it bit: Timeline Cards: footage in, ready to cut

### CFI-S03: The speech-to-text dropped the middle of long spans and ran past the end.
- Why: Long spans lost their middle, and forced English invented about 25 seconds past the audio's real end.
- Must: Mixed-language passes run in short windows of about 12 seconds, and nothing timed past the audio's real end is kept.
- Tool: faster-whisper large-v3-turbo
- Where it bit: Timeline Cards: footage in, ready to cut

### CFI-S04: The speech-to-text's voice filter removed an interviewer's quiet questions.
- Why: Its voice-activity filter drops quiet speech; on one interview almost every off-mic question vanished, 14 minutes of them.
- Must: Stretches with sound but no words are re-run without the filter, and invented filler from that run is rejected.
- Tool: faster-whisper (VAD filter)
- Where it bit: Timeline Cards: footage in, ready to cut

### CFI-S05: Re-transcribing quiet stretches invents subtitle credits and repeats.
- Why: Run on quiet audio without its speech filter, it produced phantom lines such as subtitle-site credits and verbatim repeats of earlier lines.
- Must: Lines recovered from quiet stretches are checked for known phantom phrases and exact repeats and dropped before they reach a transcript.
- Tool: Whisper
- Where it bit: Timeline Cards: footage in, ready to cut

### CFI-S06: The speech-to-text stamps a few words across long silences and invents words.
- Why: Six characters were stamped across 72 s; near-silence returned 22 zero-length mixed-language "words"; a short extracted span hallucinates more than the full file.
- Must: Timing across silence is never trusted, zero-length words are discarded, and transcription runs on whole files, not short excerpts.
- Tool: faster-whisper
- Where it bit: Timeline Cards: footage in, ready to cut

### CFI-S07: The same clip transcribed twice gives a different number of words.
- Why: Plain sequential transcription is not deterministic: one studio clip gave 999 words in one run and 965 in another, a 3.4% spread.
- Must: Checks comparing transcripts tolerate a few percent of run-to-run difference instead of calling it a regression.
- Tool: faster-whisper
- Where it bit: Timeline Cards: footage in, ready to cut

### CFI-S08: Mandarin words come one character each, with punctuation only in sentence segments.
- Why: Joined word by word, Mandarin reads as one unbroken string; sentence boundaries exist only in the sentence-level segments, which cost about a sixth of the output.
- Must: Sentence-level text is kept beside word timing; readable text and paragraphs come from sentences, spans from words.
- Tool: faster-whisper (Mandarin word timestamps)
- Where it bit: Timeline Cards: footage in, ready to cut

### CFI-S09: Batched transcription was three times faster and silently lost a fifth of a piece.
- Why: Batched mode ran 2.9x faster (94x against 32x realtime) but lost 5.1% of words overall, 21.7% on a studio piece with music, and merged 100 segments into 14.
- Must: A speed-up is accepted only if per-clip word counts stay within 1% and timings within 0.10 s at p95; anything that loses words is opt-in.
- Tool: faster-whisper BatchedInferencePipeline
- Where it bit: Timeline Cards: footage in, ready to cut

### CFI-S10: Transcription crawled and hung while Resolve made proxies on the same GPU.
- Why: Sharing the GPU with Blackmagic Proxy Generator, half-precision transcription ran at real time and hung; 8-bit mixed precision ran eight times faster.
- Must: Transcription keeps several times real time on a shared GPU by choosing a lighter precision, or says plainly that it is waiting.
- Tool: faster-whisper (CTranslate2 compute type float16 versus int8_float16)
- Where it bit: Timeline Cards: footage in, ready to cut

### CFI-S12: A converted speech model silently transcribed with the wrong vocabulary.
- Why: A converted model missing its vocabulary file fell back to a small default vocabulary with no error; the correct size was 51,865.
- Must: Loading a speech model checks its vocabulary matches the model and refuses to transcribe when it does not.
- Tool: faster-whisper with CTranslate2 model conversion
- Where it bit: Timeline Cards: footage in, ready to cut

### CFI-S13: Singing and chanting come out as gaps with no text.
- Why: Singing, chanting and an announcer's call left caption gaps, so they could only be found by ear.
- Must: Long stretches of sound with no text are marked, so the editor can find sung or chanted material.
- Tool: Whisper
- Where it bit: Timeline Cards: footage in, ready to cut

### CFI-S14: Taiwanese Hokkien needs its own model, which writes rough Mandarin characters.
- Why: The standard model has no Hokkien; a fine-tune writes Han characters at about 11 times real time, strips all punctuation and gets about 30% of characters wrong.
- Must: Hokkien interviews use a model chosen per interview, their transcripts are marked first drafts, and punctuation is restored before splitting or translating.
- Tool: Breeze-ASR (Whisper fine-tune for Taiwanese)
- Where it bit: Timeline Cards: footage in, ready to cut

### SRT-S17: Local transcription takes 6 to 13 seconds per 10-minute file on a desktop GPU.
- Why: The large turbo model on an RTX 3080 agreed with the paid service on 78-90% of phrases and on timing within 0.02 s.
- Must: Local transcription stands in for the paid service for speech matching, at about 6-13 s per 10 minutes of audio.
- Tool: Whisper large-v3-turbo
- Where it bit: The Footage Sorter and camera cards
