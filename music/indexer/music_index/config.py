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
import shutil
from pathlib import Path

# UnknownShareError is re-exported for the same reason PathTraversalError is:
# resolve_path raises either one, and a caller that catches only the first
# dies on a row with a NULL or foreign `share` (MUSIC-12, 2026-08-11).
from musicweb.config import (  # noqa: F401
    DATA_ROOT, DB_PATH, MUSIC_ROOT, SHARE, PathTraversalError,
    UnknownShareError, resolve_path, safe_join, share_root,
)

def _tool(name):
    """ffmpeg/ffprobe: explicit env var, else PATH, else the bare name.

    2026-08-17, COMMERCIAL_READINESS.md item 10: these defaulted to one
    operator's `C:\\Users\\<name>\\tools\\ffmpeg\\bin\\…` -- personal identity in
    tracked source, and a path no other machine has, so every other rig failed
    with a FileNotFoundError naming a stranger's home directory. There is no
    hardcoded default any more. A rig that keeps a private ffmpeg build sets
    FFMPEG/FFPROBE (or puts it on PATH) in its own environment or the
    git-ignored site.toml, never here. Falling back to the bare name keeps the
    unresolved failure pointing at the tool rather than at a bogus path;
    `require_tools()` turns it into an instruction for callers that ask first.
    """
    return os.environ.get(name.upper()) or shutil.which(name) or name


FFMPEG = _tool('ffmpeg')
FFPROBE = _tool('ffprobe')


class FfmpegNotConfigured(RuntimeError):
    """Neither FFMPEG/FFPROBE nor PATH resolves the tools this indexer shells out to."""


def require_tools():
    """Raise FfmpegNotConfigured, by name, before a long run shells out blind."""
    missing = [n for n, v in (('ffmpeg', FFMPEG), ('ffprobe', FFPROBE))
               if not (os.path.isabs(v) and os.path.isfile(v)) and shutil.which(v) is None]
    if missing:
        raise FfmpegNotConfigured(
            f"music indexing needs {' and '.join(missing)}: not on PATH, and no "
            "FFMPEG/FFPROBE override is set. Install ffmpeg or point FFMPEG/FFPROBE "
            "at it in this machine's environment (not in the repo)."
        )

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

# Where transformers/huggingface keep the CLAP weights (~600 MB for
# larger_clap_music_and_speech). Empty means their own default, which inside a
# container is a layer thrown away on every start -- tools/Dockerfile.indexer-gpu
# mounts a volume and points this at it (2026-08-17, COMMERCIAL_READINESS.md
# item 14). Exported into the environment rather than passed per
# `from_pretrained` call because CLAP is loaded from three modules here and
# transformers reads HF_HOME at import time in places.
MODEL_CACHE = os.environ.get('MUSIC_MODEL_CACHE') or os.environ.get('HF_HOME') or ''
if MODEL_CACHE:
    os.environ.setdefault('HF_HOME', MODEL_CACHE)


class DbPathNotConfigured(RuntimeError):
    """No index was named, and guessing one is how a drain silently does nothing."""


def require_db_path(explicit=None):
    """Which index this run writes to, or refuse by name. -> Path.

    Required, not defaulted (2026-08-17, COMMERCIAL_READINESS.md item 14). The
    old fallback -- `music/web/data/music.db`, wherever this checkout happens to
    be -- is the wrong database on the two occasions it matters most: a drain
    has to run against the copy pulled down from the NAS (MUSIC-3, 2026-08-11:
    `--queue` opened the in-repo index and reported "nothing to analyse" while
    the editor's upload sat pending on the NAS forever), and a customer's
    library is not inside their checkout at all. An implicit run now says which
    variable would have answered the question instead of picking for itself.
    """
    if explicit:
        return Path(explicit)
    if os.environ.get('MUSIC_DB_PATH') or os.environ.get('MUSIC_DATA_ROOT'):
        # musicweb.config has already applied both, in that order of precedence.
        return Path(DB_PATH)
    raise DbPathNotConfigured(
        'no index selected. Pass --db <path> -- for a drain that is the copy '
        'pulled down from the NAS (music/web/DEPLOY.md) -- or set MUSIC_DB_PATH '
        'to the music.db this machine owns; on the base rig that is '
        '<checkout>/music/web/data/music.db. Defaulting to the in-repo index is '
        'how a drain silently reports "nothing to analyse" (MUSIC-3).')
