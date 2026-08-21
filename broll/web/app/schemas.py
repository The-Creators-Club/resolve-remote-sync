"""Pydantic request/response models for the ingest endpoints.

See SPEC.md "Web API contract" and "Claude indexing output contract".
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

QUALITY_FLAGS = {
    "shaky",
    "soft_focus",
    "overexposed",
    "underexposed",
    "noisy",
    "rolling_shutter",
}


class VideoIn(BaseModel):
    """POST /api/ingest/video body. Upserted by (share, rel_path).

    `extra="allow"` so a key this contract does not carry is VISIBLE to the
    route (which logs it) instead of being dropped by pydantic's default
    without a word (broll-5, 2026-08-21). Not "forbid": the indexer reaches
    this endpoint from set_error, i.e. while already handling a failure, and
    turning that into a 422 would replace a lost message with a lost row.
    """

    model_config = ConfigDict(extra="allow")

    share: str
    rel_path: str
    hash: str | None = None
    size_bytes: int | None = None
    duration_s: float | None = None
    fps: float | None = None
    width: int | None = None
    height: int | None = None
    codec: str | None = None
    shot_date: str | None = None
    category: str | None = None
    category_hint: str | None = None
    in_inbox: bool = False
    status: str | None = None
    # Why a clip's status is what it is. The indexer's set_error sends it with
    # every 'error' (and stage_probe with a 'skipped'), and until 2026-08-21
    # this model had no field for it: the row went to 'error' with a NULL
    # reason and the only copy of the diagnosis stayed in the indexing
    # machine's local shadow DB (broll-5). COALESCEd on the upsert, like
    # category and the sprite geometry.
    error: str | None = None
    # Written by `broll-index duplicates --apply` and `origins`, which reach
    # the web DB through this one endpoint too. Same silent drop, same fix.
    full_hash: str | None = None
    duplicate_of: int | None = None
    archive_path: str | None = None
    original_path: str | None = None
    original_size_bytes: int | None = None
    original_verified_at: str | None = None
    # The sprite sheet's real geometry, measured by the indexer's build_sprite
    # and forwarded here by HttpBackend.update_video (BROLL-1/BROLL-2,
    # 2026-08-11). Absent on every other ingest call, and COALESCEd on the
    # upsert, so a later plain scan cannot wipe what the proxy stage recorded.
    sprite_cell_w: int | None = None
    sprite_cell_h: int | None = None
    sprite_cols: int | None = None
    sprite_cells: int | None = None
    sprite_interval_s: float | None = None


class SegmentIn(BaseModel):
    t_start: float
    t_end: float
    description: str = ""
    objects: list[str] = Field(default_factory=list)
    setting: str = ""
    motion: str = ""
    onscreen_text: str = ""     # verbatim, original script (see SPEC.md
                                 # "Claude indexing output contract")
    onscreen_text_en: str = ""  # short English rendering of the above


class IndexIn(BaseModel):
    """POST /api/ingest/index body."""

    video_id: int
    themes: list[str] = Field(default_factory=list)
    quality_flags: list[str] = Field(default_factory=list)
    category_hint: str | None = None
    segments: list[SegmentIn] = Field(default_factory=list)
    model: str | None = None


class MovedIn(BaseModel):
    """POST /api/ingest/moved body."""

    video_id: int
    new_rel_path: str


# --- dashboard b-roll ingest (docs/BROLL_INGEST_PLAN.md §4.2/§4.3, 2026-08-18) --
#
# The caps are not decoration. `items` arrives from a drag-and-drop that
# traversed a folder tree in the browser, and `segments` from a local model
# nobody on this side supervises; both go through the dashboard's 4 MiB body
# cap first, but a body that fits and still describes 50,000 clips would be a
# request this single-worker process spends a minute inside.
MAX_BATCH_ITEMS = 2000
MAX_NAME_CHARS = 255
MAX_SEGMENTS = 500


class IngestItemIn(BaseModel):
    """One clip in a drop, as the SPA describes it before anything has run."""

    local_id: str = Field(default="", max_length=128)
    name: str = Field(max_length=MAX_NAME_CHARS)
    # Sub-folder below the shoot root. Sanitised server-side (every component
    # through archive_names.safe_name, `..` dropped) -- it ends up in a path a
    # companion hands to rclone.
    rel_dir: str = Field(default="", max_length=1024)
    size: int | None = None
    # xxh64(first 8MiB + last 8MiB + size), computed by the companion with the
    # indexer's own algorithm. Absent = no duplicate check for this clip.
    hash: str | None = Field(default=None, max_length=64)
    source: Literal["upload", "path"] = "upload"
    # Carried through from a pre-check the editor then confirmed. Advisory: the
    # server does not act on it beyond recording what they were told.
    duplicate_of: int | None = None


class IngestPrecheckIn(BaseModel):
    """POST /api/ingest-batches/precheck. Read-only; reserves nothing."""

    share: str = Field(max_length=MAX_NAME_CHARS)
    keep_subfolders: bool = True
    items: list[IngestItemIn] = Field(default_factory=list, max_length=MAX_BATCH_ITEMS)


class IngestBatchCreateIn(BaseModel):
    """POST /api/ingest-batches."""

    share: str = Field(max_length=MAX_NAME_CHARS)
    # v1 files every ingested shoot as own footage (plan §9 decision 1);
    # Downloads/category allocation at result time is the follow-up. Accepted
    # on the wire so that follow-up is not a body change.
    collection: str | None = None
    settings: dict = Field(default_factory=dict)
    items: list[IngestItemIn] = Field(default_factory=list, max_length=MAX_BATCH_ITEMS)


class UploadPausedIn(BaseModel):
    paused: bool = True


class ClaimIn(BaseModel):
    """POST …/claim. NOTE the absence of an `editor` field: the leaseholder is
    the name the verified X-CCSync-Identity carries and nothing else. Two
    sources for one fact is how the wrong one wins (H5)."""

    machine: str = Field(default="", max_length=MAX_NAME_CHARS)
    companion_version: str = Field(default="", max_length=64)
    tier: Literal["good", "best"] = "good"
    # Whatever the companion's capability probe found (GPU, VRAM, ffmpeg,
    # rclone). Recorded in the log, not enforced: the machine that knows what a
    # clip costs is the one that declines its own claim (the ytdl free-space
    # lesson, plan §7).
    capabilities: dict = Field(default_factory=dict)


class HeartbeatIn(BaseModel):
    pass


class ItemStatusIn(BaseModel):
    """POST …/items/{iuid}/status -- one checkpoint."""

    state: str
    stage_percent: int | None = Field(default=None, ge=0, le=100)
    error: str | None = Field(default=None, max_length=2000)
    attempts: int | None = Field(default=None, ge=0)
    hash: str | None = Field(default=None, max_length=64)
    # ffprobe's answers, once the companion has them: duration_s, fps, width,
    # height, codec, shot_date.
    probe: dict | None = None


class ItemResultIn(BaseModel):
    """POST …/items/{iuid}/result -- what the local model saw.

    Reuses SegmentIn, so the shape the vendored `describe_video` produces is
    the shape `/api/ingest/index` already accepts: one contract, two doors.
    """

    segments: list[SegmentIn] = Field(default_factory=list, max_length=MAX_SEGMENTS)
    themes: list[str] = Field(default_factory=list, max_length=64)
    quality_flags: list[str] = Field(default_factory=list, max_length=16)
    category_hint: str | None = None
    model: str | None = None
    duration_s: float | None = None
    fps: float | None = None
    width: int | None = None
    height: int | None = None
    codec: str | None = None
    shot_date: str | None = None
    # Measured off the sheet the companion just wrote, never re-derived -- the
    # browser's old source-derived heuristics were wrong on 6,783 of 7,117
    # sheets (BROLL-1/BROLL-2, migrations/009).
    sprite_cell_w: int | None = None
    sprite_cell_h: int | None = None
    sprite_cols: int | None = None
    sprite_cells: int | None = None
    sprite_interval_s: float | None = None


class UploadedFileIn(BaseModel):
    """One file the companion says it put in the archive. `rel` is relative to
    the archive root and is stat'ed there before anything is believed."""

    rel: str = Field(max_length=1024)
    size: int | None = None


class ItemUploadedIn(BaseModel):
    files: list[UploadedFileIn] = Field(default_factory=list, max_length=16)
    original_uploaded: bool = False


class ReleaseIn(BaseModel):
    state: Literal["done", "failed", "cancelled"] = "done"
    # Free-form; stored truncated in ingest_batches.error, which the fleet grid
    # shows in a tooltip.
    summary: dict | str | None = None


class ShareRootIn(BaseModel):
    """One share's origin facts, pushed by the indexer (POST /api/ingest/shares)."""

    share: str
    root: str
    # Mirrors indexer ShareConfig.source. For a 'proxies' share the archived
    # original IS the Proxy/*.mov, so a conform must not hunt for camera files
    # that were deliberately left behind.
    # Validated here, not left to the table's CHECK: a bad value should come
    # back as a 422 naming the field, not surface as an unhandled DB error.
    source: Literal["originals", "proxies"] = "originals"
    description: str = ""
    indexed: bool = True


# --- client folders (docs/CLIENT_FOLDERS.md, 2026-08-18) -------------------------
# Lengths are enforced in app.client_folders (one place, shared with any
# non-HTTP caller); these models only shape the JSON.


class ClientFolderCreateIn(BaseModel):
    title: str
    description: str = ""
    contact: str = ""
    expires_at: str | None = None


class ClientFolderUpdateIn(BaseModel):
    """PATCH semantics: a field left out is left alone. `expires_at` sent as
    an explicit null clears the expiry -- see routes_client_folders."""

    title: str | None = None
    description: str | None = None
    contact: str | None = None
    expires_at: str | None = None


class ClientFolderItemsIn(BaseModel):
    video_ids: list[int] = Field(min_length=1, max_length=500)


class ClientFolderNoteIn(BaseModel):
    note: str = ""


class ClientFolderOrderIn(BaseModel):
    video_ids: list[int] = Field(max_length=500)


class ClientShareSettingsIn(BaseModel):
    public_base_url: str = ""
