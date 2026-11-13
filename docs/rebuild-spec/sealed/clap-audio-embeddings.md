# Sealed notes: clap-audio-embeddings

SEALED. Not part of the pack. Released to the rebuild only after its own committed design names this tool. 3 notes.

### MUS-S01: Music tags computed on an editor's computer differed from the studio server's.
- Why: One variant of the analyser randomises its audio front end, so a slightly different spectrogram yields a plausible fingerprint of the wrong audio; the plain variant ran 93 ms per 10 s on CPU.
- Must: A track analysed on any editor's computer gets the same fingerprint, tags and search results as if analysed on the studio server.
- Tool: CLAP (laion/larger_clap_music_and_speech) audio tower exported to ONNX
- Where it bit: Music

### MUS-S02: Raw similarity scores from the audio analyser meant nothing in absolute terms.
- Why: Scores sit in a narrow band with correct ordering; the best 10-second window beat the track average (40% vs 20%); the analyser hears quietness poorly.
- Must: Music filters use rank within the library, and quiet beds are found by an energy control rather than the word "quiet".
- Tool: CLAP audio embeddings
- Where it bit: Music

### MUS-S03: Similar tracks came from one stock library, and removing that bias hurt text search.
- Why: The analyser hears codec, and one library was mostly lossless; applying the bias correction to typed queries halved top-10 accuracy, 40% to 20%.
- Must: Similar-track results are not dominated by one source or codec, and the source-bias correction never applies to typed text queries.
- Tool: CLAP audio-text embeddings with a source-bias projection
- Where it bit: Music
