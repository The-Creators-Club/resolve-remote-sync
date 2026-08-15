"""Storage abstraction the CLI commands drive.

Two backends implement this (see SPEC.md "Indexer CLI contract" / "Web API contract"):

- SqliteBackend: co-located dev mode. Writes schema.sql's tables directly.
- HttpBackend: talks to the web app via /api/ingest/* endpoints.

No ORM — plain dicts (sqlite3.Row -> dict) in, plain dicts out.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from ..transcribe import TranscriptCue


class Storage(ABC):
    @abstractmethod
    def upsert_video(self, share: str, rel_path: str, **fields: Any) -> int:
        """Insert or update the videos row for (share, rel_path). Returns the video id."""

    @abstractmethod
    def get_video(self, video_id: int) -> dict[str, Any] | None: ...

    @abstractmethod
    def get_video_by_path(self, share: str, rel_path: str) -> dict[str, Any] | None: ...

    @abstractmethod
    def videos_by_status(self, statuses: list[str], limit: int | None = None) -> list[dict[str, Any]]:
        """Videos in one of `statuses`, excluding confirmed duplicates (`duplicate_of`
        IS NOT NULL) — see broll_index/duplicates.py and pipeline.py's run_pipeline.
        A known duplicate must never reach the job queue: it would spend model calls
        describing footage already described under its canonical row."""

    @abstractmethod
    def sortable_videos(self) -> list[dict[str, Any]]:
        """Videos eligible for `sort`: in_inbox=1, category set, status='indexed'."""

    @abstractmethod
    def all_videos(self) -> list[dict[str, Any]]:
        """Every videos row, for `rebase` hash matching."""

    @abstractmethod
    def segment_counts(self) -> dict[int, int]:
        """video_id -> number of indexed segments, for `rebase` duplicate ranking."""

    @abstractmethod
    def delete_video(self, video_id: int) -> None:
        """Delete a videos row and its cascaded segments/themes/flags."""

    @abstractmethod
    def update_video(self, video_id: int, **fields: Any) -> None: ...

    @abstractmethod
    def set_error(self, video_id: int, message: str) -> None: ...

    @abstractmethod
    def write_index_result(
        self,
        video_id: int,
        *,
        themes: list[str],
        quality_flags: list[str],
        category_hint: str | None,
        segments: list[dict[str, Any]],
        model: str,
    ) -> None:
        """Replace themes/quality_flags/segments for a video and mark status='indexed'.

        Each segment dict follows the v2 contract in SPEC.md ("Claude indexing output
        contract"): alongside description/objects/setting/motion it carries
        `onscreen_text` (verbatim, original script) and `onscreen_text_en` (English
        rendering), both required keys, defaulted to "" upstream by
        claude_client.validate_contract if a model omits them. Implementations must
        persist both fields.
        """

    @abstractmethod
    def write_transcript(
        self, video_id: int, cues: list[TranscriptCue], lang: str | None
    ) -> None:
        """Replace transcript_segments for a video atomically.

        Additive enrichment, independent of the videos.status flow driven by
        write_index_result/set_error: this must set videos.transcribed_at (and
        transcript_lang) but must NEVER touch videos.status. See
        broll_index/transcribe.py and docs/indexing-findings.md.
        """

    @abstractmethod
    def get_transcript(self, video_id: int) -> list[TranscriptCue]:
        """All transcript cues for a video, ordered by t_start."""

    # -- hybrid search (v4): CJK normalization + semantic embeddings ------

    @abstractmethod
    def get_segments(self, video_id: int) -> list[dict[str, Any]]:
        """All `segments` rows for a video (raw fields, id, and search_norm), ordered by
        t_start. See broll_index/normalize.py and broll_index/pipeline.py's stage_embed."""

    @abstractmethod
    def get_transcript_segments(self, video_id: int) -> list[dict[str, Any]]:
        """All `transcript_segments` rows for a video (raw fields, id, and search_norm),
        ordered by t_start. Distinct from get_transcript, which returns TranscriptCue
        objects without id/search_norm for the callers that only need cue text/timing."""

    @abstractmethod
    def update_search_norm(self, source: str, source_id: int, search_norm: str) -> None:
        """Write the normalized keyword blob (broll_index/normalize.searchable_blob) back
        onto one row. `source` is 'segment' or 'transcript' (matching embeddings.source)."""

    # The two batch twins below are deliberately CONCRETE: the default is the
    # single-row loop every backend already implements, so a backend only
    # overrides them if it can actually do better. SqliteBackend can (one
    # executemany, one search-generation bump, one commit per video instead of
    # one transaction, fsync and `meta` UPDATE per row — ~83,000 of them for a
    # full re-embed of this corpus, where ~7,100 will do; BROLL-IDX-8,
    # 2026-08-14). HttpBackend inherits the loop and so keeps raising its
    # "not supported over the ingest API" NotImplementedError unchanged.
    def update_search_norms(self, rows: list[tuple[str, int, str]]) -> None:
        """update_search_norm for a whole video's rows: (source, source_id, search_norm)."""
        for source, source_id, search_norm in rows:
            self.update_search_norm(source, source_id, search_norm)

    def upsert_embeddings(
        self, rows: list[tuple[str, int, int, str, int, bytes]]
    ) -> None:
        """upsert_embedding for a whole video's rows: (source, source_id, video_id, model, dim, vec)."""
        for source, source_id, video_id, model, dim, vec in rows:
            self.upsert_embedding(source, source_id, video_id, model, dim, vec)

    @abstractmethod
    def get_embedding_models(self, video_id: int) -> dict[tuple[str, int], str]:
        """(source, source_id) -> model for every `embeddings` row already stored for this
        video — lets stage_embed skip rows already embedded with the current model and
        re-embed rows whose stored model differs (a model change in config)."""

    @abstractmethod
    def upsert_embedding(
        self, source: str, source_id: int, video_id: int, model: str, dim: int, vec: bytes
    ) -> None:
        """Insert or replace the `embeddings` row for (source, source_id)."""

    @abstractmethod
    def record_moved(self, video_id: int, new_rel_path: str) -> None:
        """Update rel_path after `sort` moves a file; clears in_inbox, sets status='sorted'."""

    @abstractmethod
    def all_themes(self) -> list[str]:
        """Every theme string ever written, for `taxonomy propose` clustering."""

    @abstractmethod
    def themes_with_video_ids(self) -> list[tuple[int, str]]:
        """(video_id, theme) for indexed videos, for rule-based category assignment.

        Distinct from all_themes(), which flattens away the video a theme came
        from — fine for clustering a proposal, useless for deciding which folder
        a specific clip belongs in."""

    @abstractmethod
    def get_categories(self) -> list[dict[str, Any]]: ...

    @abstractmethod
    def apply_taxonomy(self, categories: list[dict[str, Any]]) -> None: ...
