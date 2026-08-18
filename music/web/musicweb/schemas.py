"""Request models for the music ingest batch APIs.

docs/MUSIC_INGEST_PLAN.md step 2, 2026-08-18. The first pydantic models in this
app: /api/search and friends take query parameters, and the drag-and-drop
upload route takes multipart, so nothing here needed a body model before.

The caps are not decoration. `items` arrives from a drag-and-drop that
traversed a folder tree in the browser, and an embedding arrives base64'd from
a machine nobody on this side supervises. Both go through the dashboard's body
cap first, but a body that fits and still describes 50,000 tracks would be a
request this single-worker process spends a minute inside.

**Embeddings ride as base64 of raw little-endian float32**, not as a JSON array
of 512 numbers: the array form is ~9 x the bytes and every one of them is
parsed into a Python float and thrown away. `db.to_blob` writes exactly these
bytes, so the wire format and the stored format are the same thing with a
base64 in between.
"""
import base64

from pydantic import BaseModel, Field

MAX_NAME_CHARS = 255
# 512 float32 today; the cap is generous enough for any CLAP variant and small
# enough that a body claiming a megabyte of embedding is refused as nonsense.
MAX_EMBEDDING_B64 = 32_768
# audio.PEAK_BUCKETS is 900 uint8; base64 of that is 1200 characters.
MAX_PEAKS_B64 = 8_192
# MAX_WINDOWS is 12 in the indexer; allow some headroom for a longer cue.
MAX_WINDOWS = 64


class _B64Mixin:
    """Decode a base64 field, or 422 with the field named.

    A refusal, never an exception: this is attacker-shaped input on a route
    that a fleet token gets to, and a 500 with a traceback is the wrong answer
    to bad base64 (DASH-5's lesson, one layer up).
    """

    @staticmethod
    def _decode(value, what):
        from fastapi import HTTPException
        if not value:
            return b''
        try:
            return base64.b64decode(value, validate=True)
        except (ValueError, TypeError) as exc:
            raise HTTPException(422, {
                'detail': f'{what} is not valid base64: {exc}',
                'reason': 'encoding'}) from None


class IngestItemIn(BaseModel):
    """One dropped file, as the SPA describes it before anything has run."""

    local_id: str = Field(default='', max_length=128)
    name: str = Field(max_length=MAX_NAME_CHARS)
    size: int | None = None
    # ffprobe's duration, measured on the editor's machine. Feeds the
    # re-encode defence, which is the only one that can see an .ogg re-encode
    # of a track already held.
    duration: float | None = None
    # blake2b-16 over the whole file -- db.content_hash's digest.
    content_hash: str | None = Field(default=None, max_length=64)
    source: str = Field(default='upload', pattern='^(upload|path)$')


class IngestPrecheckIn(BaseModel):
    """POST /api/ingest-batches/precheck. Read-only; reserves nothing."""

    items: list[IngestItemIn] = Field(default_factory=list, max_length=500)


class IngestBatchCreateIn(BaseModel):
    """POST /api/ingest-batches."""

    settings: dict = Field(default_factory=dict)
    items: list[IngestItemIn] = Field(default_factory=list, max_length=500)


class UploadPausedIn(BaseModel):
    paused: bool = True


class ClaimIn(BaseModel):
    """POST .../claim. NOTE the absence of an `editor` field: the leaseholder
    is the name the verified X-CCSync-Identity carries and nothing else. Two
    sources for one fact is how the wrong one wins (H5)."""

    machine: str = Field(default='', max_length=MAX_NAME_CHARS)
    companion_version: str = Field(default='', max_length=64)
    # Whatever the companion's probe found (ffmpeg, the CLAP sidecar, free
    # space). Logged, not enforced: the machine that knows what a track costs
    # is the one that declines its own claim.
    capabilities: dict = Field(default_factory=dict)


class HeartbeatIn(BaseModel):
    pass


class ItemStatusIn(BaseModel):
    """POST .../items/{iuid}/status -- one checkpoint."""

    state: str
    stage_percent: int | None = Field(default=None, ge=0, le=100)
    error: str | None = Field(default=None, max_length=2000)
    attempts: int | None = Field(default=None, ge=0)
    content_hash: str | None = Field(default=None, max_length=64)
    transcoded: bool | None = None
    # ffprobe's answers: duration_s, samplerate, channels, codec.
    probe: dict | None = None


class WindowIn(BaseModel, _B64Mixin):
    """One 10 s analysis window's embedding."""

    idx: int = Field(ge=0)
    t0: float = 0.0
    t1: float = 0.0
    vector: str = Field(default='', max_length=MAX_EMBEDDING_B64)

    def vector_bytes(self):
        return self._decode(self.vector, 'a window vector')


class ItemResultIn(BaseModel, _B64Mixin):
    """POST .../items/{iuid}/result -- what the editor's machine computed.

    Everything `index_music.analyse_one` produces except the file itself: the
    pooled track embedding, the per-window vectors, the waveform, the probe and
    the DSP features. The server writes the `tracks` row from this and then
    scores the library around it.
    """

    # The pooled, L2-normalised track vector -- base64 of raw float32.
    embedding: str = Field(default='', max_length=MAX_EMBEDDING_B64)
    dim: int | None = None
    model: str | None = Field(default=None, max_length=200)
    # The final name the companion landed the file under, if it differs from
    # the original (an .ogg it transcoded). The server still allocates the
    # authoritative name -- this is the stem it prefers.
    name: str | None = Field(default=None, max_length=MAX_NAME_CHARS)
    transcoded: bool = False
    content_hash: str | None = Field(default=None, max_length=64)
    size_bytes: int | None = None
    # From the DECODED sample count, not from ffprobe: an .aac duration derived
    # from bitrate x filesize is wrong in both directions, and the re-encode
    # duplicate check matches on it (index_music.analyse_one's note).
    duration: float | None = None
    bpm: float | None = None
    music_key: str | None = Field(default=None, max_length=32)
    key_conf: float | None = None
    lufs: float | None = None
    peak_db: float | None = None
    probe: dict | None = None
    # audio.peaks' uint8-per-bucket overview, base64.
    peaks: str = Field(default='', max_length=MAX_PEAKS_B64)
    windows: list[WindowIn] = Field(default_factory=list, max_length=MAX_WINDOWS)

    def embedding_bytes(self):
        return self._decode(self.embedding, 'the embedding')

    def peaks_bytes(self):
        return self._decode(self.peaks, 'the waveform')


class ItemUploadedIn(BaseModel):
    """POST .../items/{iuid}/uploaded.

    No path field, deliberately, unlike b-roll's list of archive-relative
    files: a music item owns exactly ONE file and the server allocated its name
    itself at `result`. Nothing about where to look comes off the wire, so
    there is no traversal to defend against -- only a size to agree on.
    """

    size: int | None = None


class ReleaseIn(BaseModel):
    state: str = Field(default='done', pattern='^(done|failed|cancelled)$')
    # Free-form; stored truncated in ingest_batches.error, which the fleet grid
    # shows in a tooltip.
    summary: dict | str | None = None
