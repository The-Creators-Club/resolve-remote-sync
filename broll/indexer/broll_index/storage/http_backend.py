"""HTTP ingest storage backend (indexer running against a remote web app).

SPEC.md's ingest contract only defines three write endpoints:
    POST /api/ingest/video   -- upsert video row by (share, rel_path), returns {id}
    POST /api/ingest/index   -- replace themes/quality_flags/segments/category_hint
    POST /api/ingest/moved   -- update rel_path after a category-sort move

There is deliberately no read/list endpoint in that contract (the web API's other GET
routes are for the frontend: /api/search, /api/videos/{id}, /api/categories, /api/shares).
That means a remote indexer has no way to ask "which videos are still `discovered`?" over
HTTP. Rather than invent an undocumented endpoint on web/ (out of scope for this
component), this backend keeps its own local sqlite shadow (schema.sql applied, same as
SqliteBackend) purely as queue-state bookkeeping: every write goes to the shadow db AND is
POSTed to the remote ingest endpoint, and all reads (videos_by_status, sortable_videos,
etc.) are served from the shadow db. The remote id returned by /api/ingest/video is
intentionally *not* assumed to equal the local id; they're independent id spaces.

`apply_taxonomy` has no ingest endpoint at all in the contract, so in this backend it
updates the local shadow only and raises NotImplementedError to make that limitation
loud rather than silently leaving the remote `categories` table unmodified.
`write_transcript` is the same story — see its docstring below.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import requests

from ..transcribe import TranscriptCue
from .base import Storage
from .sqlite_backend import SqliteBackend


class HttpBackend(Storage):
    def __init__(
        self,
        base_url: str,
        token: str,
        local_state_path: str | Path,
        schema_path: str | Path | None = None,
        session: requests.Session | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.session = session or requests.Session()
        self.session.headers.update({"X-Ingest-Token": token})
        self._local = SqliteBackend(local_state_path, schema_path=schema_path)
        # bug-broll-2 (2026-09-25): local shadow id -> the canonical id the
        # web app answered /ingest/video with. The two are independent id
        # spaces (see the module docstring), and write_index_result and
        # record_moved used to post the LOCAL one, which in the canonical
        # database names some other clip. A table in the shadow file rather
        # than a dict, because the scan that learns the id and the index run
        # that needs it are usually different processes.
        self._local.conn.execute(
            "CREATE TABLE IF NOT EXISTS http_remote_ids ("
            "local_id INTEGER PRIMARY KEY, remote_id INTEGER NOT NULL)")
        self._local.conn.commit()

    def _remember_remote_id(self, local_id: int, resp: Any) -> None:
        try:
            remote = resp.json().get("id")
        except Exception:  # noqa: BLE001 - a body we cannot read teaches us nothing
            return
        if isinstance(remote, int) and not isinstance(remote, bool):
            self._local.conn.execute(
                "INSERT INTO http_remote_ids (local_id, remote_id) VALUES (?, ?) "
                "ON CONFLICT(local_id) DO UPDATE SET remote_id = excluded.remote_id",
                (local_id, remote))
            self._local.conn.commit()

    def _remote_ref(self, local_id: int) -> dict[str, Any]:
        """What names this clip to the web app: its canonical id, plus the
        (share, rel_path) a current server resolves by instead (bug-broll-2).

        With no recorded canonical id the id sent is 0, which no row carries:
        an older server that reads only the id then answers 404, loudly,
        rather than writing onto whichever canonical clip shares the LOCAL
        number. A current server resolves by the path and never reads it.
        """
        row = self._local.conn.execute(
            "SELECT remote_id FROM http_remote_ids WHERE local_id = ?",
            (local_id,)).fetchone()
        video = self._local.get_video(local_id) or {}
        return {"video_id": int(row[0]) if row is not None else 0,
                "share": video.get("share"), "rel_path": video.get("rel_path")}

    def close(self) -> None:
        self._local.close()

    # -- videos -----------------------------------------------------------

    def upsert_video(self, share: str, rel_path: str, **fields: Any) -> int:
        video_id = self._local.upsert_video(share, rel_path, **fields)
        payload = {"share": share, "rel_path": rel_path, **fields}
        resp = self.session.post(f"{self.base_url}/ingest/video", json=payload, timeout=30)
        resp.raise_for_status()
        self._remember_remote_id(video_id, resp)
        return video_id

    def get_video(self, video_id: int) -> dict[str, Any] | None:
        return self._local.get_video(video_id)

    def get_video_by_path(self, share: str, rel_path: str) -> dict[str, Any] | None:
        return self._local.get_video_by_path(share, rel_path)

    def videos_by_status(self, statuses: list[str], limit: int | None = None) -> list[dict[str, Any]]:
        return self._local.videos_by_status(statuses, limit)

    def sortable_videos(self) -> list[dict[str, Any]]:
        return self._local.sortable_videos()

    def all_videos(self) -> list[dict[str, Any]]:
        return self._local.all_videos()

    def segment_counts(self) -> dict[int, int]:
        return self._local.segment_counts()

    def delete_video(self, video_id: int) -> None:
        # The ingest contract (SPEC.md) has no delete endpoint, so this can only
        # affect the local shadow. `rebase --apply` is refused in api mode by the
        # CLI for exactly this reason; see rebase.py.
        raise NotImplementedError(
            "deleting videos is not supported over the ingest API — run rebase against "
            "the co-located sqlite backend instead"
        )

    def update_video(self, video_id: int, **fields: Any) -> None:
        self._local.update_video(video_id, **fields)
        video = self._local.get_video(video_id)
        if video is None:
            return
        payload = {"share": video["share"], "rel_path": video["rel_path"], **fields}
        resp = self.session.post(f"{self.base_url}/ingest/video", json=payload, timeout=30)
        resp.raise_for_status()
        self._remember_remote_id(video_id, resp)

    def set_error(self, video_id: int, message: str) -> None:
        self.update_video(video_id, status="error", error=message)

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
        self._local.write_index_result(
            video_id,
            themes=themes,
            quality_flags=quality_flags,
            category_hint=category_hint,
            segments=segments,
            model=model,
        )
        payload = {
            **self._remote_ref(video_id),
            "themes": themes,
            "quality_flags": quality_flags,
            "category_hint": category_hint,
            # segments already carry v2's onscreen_text/onscreen_text_en keys (defaulted
            # to "" by claude_client.validate_contract) — forwarded to the ingest
            # endpoint unchanged, no field allowlist here.
            "segments": segments,
        }
        resp = self.session.post(f"{self.base_url}/ingest/index", json=payload, timeout=60)
        resp.raise_for_status()

    def write_transcript(
        self, video_id: int, cues: list[TranscriptCue], lang: str | None
    ) -> None:
        # SPEC.md's ingest contract has no transcript endpoint (see the module docstring
        # above for why the ingest contract only covers /video, /index, /moved). Write to
        # the local shadow so the indexer's own queue bookkeeping stays consistent, then
        # fail loudly rather than silently leaving the remote web app's database stale.
        self._local.write_transcript(video_id, cues, lang)
        raise NotImplementedError(
            "writing transcripts is not supported over the ingest API — run the "
            "'transcribe' stage against the co-located sqlite backend instead, or extend "
            "web/'s ingest contract (and SPEC.md) with a transcript endpoint first"
        )

    def get_transcript(self, video_id: int) -> list[TranscriptCue]:
        return self._local.get_transcript(video_id)

    # -- hybrid search (v4): CJK normalization + semantic embeddings ------
    #
    # Same story as write_transcript/apply_taxonomy above: SPEC.md's ingest contract has
    # no endpoint for search_norm or embeddings, so the reads are served from the local
    # shadow (harmless — it's the indexer's own bookkeeping copy) and the writes go to
    # the local shadow too, then raise NotImplementedError rather than silently leaving
    # the remote web app's database stale.

    def get_segments(self, video_id: int) -> list[dict[str, Any]]:
        return self._local.get_segments(video_id)

    def get_transcript_segments(self, video_id: int) -> list[dict[str, Any]]:
        return self._local.get_transcript_segments(video_id)

    def update_search_norm(self, source: str, source_id: int, search_norm: str) -> None:
        self._local.update_search_norm(source, source_id, search_norm)
        raise NotImplementedError(
            "writing search_norm is not supported over the ingest API — run the 'embed' "
            "stage against the co-located sqlite backend instead, or extend web/'s ingest "
            "contract (and SPEC.md) with a normalization endpoint first"
        )

    def get_embedding_models(self, video_id: int) -> dict[tuple[str, int], str]:
        return self._local.get_embedding_models(video_id)

    def upsert_embedding(
        self, source: str, source_id: int, video_id: int, model: str, dim: int, vec: bytes
    ) -> None:
        self._local.upsert_embedding(source, source_id, video_id, model, dim, vec)
        raise NotImplementedError(
            "writing embeddings is not supported over the ingest API — run the 'embed' "
            "stage against the co-located sqlite backend instead, or extend web/'s ingest "
            "contract (and SPEC.md) with an embeddings endpoint first"
        )

    def record_moved(self, video_id: int, new_rel_path: str) -> None:
        # The reference is taken BEFORE the local rename: the web app finds
        # the clip by where it is moving FROM (bug-broll-2).
        ref = self._remote_ref(video_id)
        self._local.record_moved(video_id, new_rel_path)
        resp = self.session.post(
            f"{self.base_url}/ingest/moved",
            json={**ref, "new_rel_path": new_rel_path},
            timeout=30,
        )
        resp.raise_for_status()

    def all_themes(self) -> list[str]:
        return self._local.all_themes()

    def themes_with_video_ids(self) -> list[tuple[int, str]]:
        return self._local.themes_with_video_ids()

    def get_categories(self) -> list[dict[str, Any]]:
        resp = self.session.get(f"{self.base_url}/categories", timeout=30)
        resp.raise_for_status()
        return resp.json()

    def apply_taxonomy(self, categories: list[dict[str, Any]]) -> None:
        self._local.apply_taxonomy(categories)
        raise NotImplementedError(
            "SPEC.md's ingest contract has no endpoint for writing `categories`; "
            "`taxonomy apply` only updated the indexer's local shadow db, NOT the web app's "
            "canonical database. Run `taxonomy apply` against a co-located `sqlite` backend, "
            "or extend web/'s ingest contract (and SPEC.md) with a categories endpoint first."
        )

    def push_shares(self, payload: list[dict]) -> None:
        """POST /api/ingest/shares — see broll_index/share_push.py for why."""
        resp = self.session.post(
            f"{self.base_url}/ingest/shares", json=payload, timeout=30
        )
        resp.raise_for_status()
