"""Index-time half of the music platform. Base rig only -- it needs the GPU.

Decode -> CLAP embed -> DSP features -> vocabulary scoring -> SQLite. Nothing
here runs in the NAS container: the container only ever embeds *text* (18 ms on
CPU), because every audio embedding, tag, axis, percentile, waveform and
source-bias axis is precomputed into the database by this package.

The web tree is put on sys.path at import because the storage layer is shared:
`musicweb.db` and `web/schema.sql` describe the database this package writes
and the web app reads. Duplicating either would let writer and reader drift,
and that drift is silent.
"""
import sys
from pathlib import Path

_WEB = Path(__file__).resolve().parents[2] / 'web'
if _WEB.is_dir() and str(_WEB) not in sys.path:
    sys.path.insert(0, str(_WEB))
