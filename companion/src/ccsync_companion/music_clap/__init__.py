"""The CLAP audio front end, VENDORED VERBATIM from the music indexer.

The companion embeds dropped music on the editor's own machine now (drag it
onto the dashboard's /music page -> this machine runs the exported CLAP audio
tower -> the vector, the waveform and the audio go to the NAS;
docs/MUSIC_INGEST_PLAN.md). Two of the three things that takes are the
indexer's, and they run HERE unmodified:

    music_models.py    the artefact catalogue (which ONNX, which sha256, how
                       big, which feed URL) -- the sidecar's download pins
    mel_numpy.py       CLAP's log-mel front end in numpy alone, driven by the
                       params JSON the exporter writes beside the ONNX

The third, the tower itself, is not code at all: it is the `.onnx` the sidecar
downloads (`music_clap_sidecar.py`).

**These two files are copies and must not be edited here.** Each carries a
header ending in `# --- vendored content below, byte-identical ---`, and
everything under that line is the indexer's bytes. `tools/release.ps1` and
`tools/release_macos.sh` refuse to build on drift and
`server/tests/test_cross_component.py` pins the same comparison in the suites,
exactly as they already do for `broll_vlm/` and `ytdl_common.py`. Fix a bug in
`music/indexer/`, then re-copy the file in below the marker.

Why copies and not an import: `music_index` brings torch, transformers and
librosa with it -- gigabytes inside a frozen single-file exe on every editor
machine -- for two modules that need nothing but the stdlib and numpy.

Why it matters more here than anywhere else the pattern is used: a drifted
parser produces an error, but a drifted MEL produces a perfectly plausible
512-dimensional vector for audio that does not sound like that. Every cosine
in the library is measured against it and nothing downstream can tell.

Nothing in this package is imported at tray start: `music_clap_sidecar.py` is
the companion's own front door (cache dir, download gates, onnxruntime session,
`embed_file`), and it imports these lazily so a machine that never ingests
music never pays for them.
"""
