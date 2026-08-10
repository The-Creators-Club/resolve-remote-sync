"""Pydantic request/response models for the ingest endpoints.

See SPEC.md "Web API contract" and "Claude indexing output contract".
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

QUALITY_FLAGS = {
    "shaky",
    "soft_focus",
    "overexposed",
    "underexposed",
    "noisy",
    "rolling_shutter",
}


class VideoIn(BaseModel):
    """POST /api/ingest/video body. Upserted by (share, rel_path)."""

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
