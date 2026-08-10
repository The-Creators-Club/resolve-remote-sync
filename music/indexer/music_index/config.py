"""Index-time settings: ffmpeg, CLAP, window geometry. Env vars override.

The paths (MUSIC_ROOT, DATA_ROOT, DB_PATH) and the whole (share, rel_path)
model are re-exported from `musicweb.config` rather than restated, so the
indexer and the web app cannot end up pointing at different databases or
disagree about what a rel_path means. That also means the database defaults to
living under `music/web/data/` -- with the tree that gets shipped to the NAS,
which is what happens to it.

Prefer `config.share_root()` over the `MUSIC_ROOT` constant in new code: the
constant is bound once at import, the function reads the live mapping.
"""
import os

from musicweb.config import (  # noqa: F401
    DATA_ROOT, DB_PATH, MUSIC_ROOT, SHARE, PathTraversalError,
    resolve_path, safe_join, share_root,
)

FFMPEG = os.environ.get('FFMPEG', r'C:\Users\alex\tools\ffmpeg\bin\ffmpeg.exe')
FFPROBE = os.environ.get('FFPROBE', r'C:\Users\alex\tools\ffmpeg\bin\ffprobe.exe')

# Folders under MUSIC_ROOT that are never indexed. _stems holds partial mixes
# (BASS/DRUMS/...) whose full versions are already in the library.
EXCLUDE_DIRS = {'_stems'}

AUDIO_EXTS = {'.wav', '.mp3', '.flac', '.aac', '.m4a', '.ogg', '.aiff', '.aif', '.opus'}

# CLAP operates on 10s of 48kHz mono audio.
SAMPLE_RATE = 48000
WINDOW_SEC = 10.0
MAX_WINDOWS = 12          # windows sampled evenly across a track
ANALYSIS_SR = 22050       # separate decode for librosa BPM/key

CLAP_MODEL = os.environ.get('CLAP_MODEL', 'laion/larger_clap_music_and_speech')
CLAP_FALLBACK = 'laion/clap-htsat-unfused'
BATCH_SIZE = int(os.environ.get('BATCH_SIZE', '16'))
