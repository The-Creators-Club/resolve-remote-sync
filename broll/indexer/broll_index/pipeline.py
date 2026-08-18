"""`broll-index run` — resumable stage pipeline: probe -> proxy -> frames -> claude.

Per SPEC.md: "per-file status transitions discovered -> probed -> proxied -> indexed
(error + message on failure, never crash the queue)". The `frames` stage doesn't have its
own status (schema.sql's status enum has no such value) — it's an intermediate step that
runs between `proxied` and the `claude` stage, and is made idempotent/resumable via a
sentinel file in its output directory rather than a DB column.

There is also a `transcribe` stage (local faster-whisper speech transcription — see
docs/indexing-findings.md). It is deliberately NOT part of the above status flow: it
never sets videos.status, doesn't gate `claude`, and its failures are logged and
swallowed rather than surfaced via `error` — a clip with no useful audio, or a machine
without whisper set up, is still a perfectly good indexed clip. See stage_transcribe.

Same story for `embed` (CJK keyword normalization + semantic embeddings — see
broll_index/normalize.py, broll_index/embed.py, migrations/004_hybrid_search.sql):
status-independent additive enrichment, never sets videos.status, never blocks another
stage, failures logged and swallowed. See stage_embed.
"""

from __future__ import annotations

import json
import functools
import logging
from pathlib import Path
from typing import Any

from . import embed, ffmpeg_tools, local_vlm, normalize, transcribe, transcript_quality
from .claude_client import InvokeFn, build_index_prompt, chunk_sheets, cap_sheets, invoke_claude, call_claude_with_retry, \
    merge_index_results, resolve_model, build_client, ClaudeCallError, is_fatal_api_error, is_rate_limited, \
    extract_reset_hint
from .config import Config
from .share_push import push_shares
from .storage.base import Storage

logger = logging.getLogger(__name__)


class FatalRunError(RuntimeError):
    """Abort the whole run: a problem no other video will survive either.

    Raised for environmental API failures (exhausted credit, bad auth). The
    queue is left exactly as it was so the run resumes cleanly once the
    underlying problem is fixed.
    """

# "transcribe" and "embed" deliberately have no entry in STAGE_PREREQ_STATUS below: both
# are additive enrichment, independent of the discovered -> probed -> proxied -> indexed
# status flow (see docs/indexing-findings.md, stage_transcribe's docstring, and
# stage_embed's docstring), so they are eligible to run regardless of a video's current
# status whenever they're in the requested stage set. "transcribe" is ordered before
# "claude" so a transcribe failure — logged and swallowed, never raised past
# stage_transcribe — can never prevent the claude stage from running in the same pass.
# "embed" is ordered after "claude" since it normalizes/embeds the segments claude just
# produced (as well as any transcript cues), but a video need not be freshly claude'd to
# be eligible — see run_pipeline's status widening below, same pattern as "transcribe".
STAGE_ORDER = ["probe", "proxy", "frames", "transcribe", "claude", "embed"]
STAGE_PREREQ_STATUS = {"probe": "discovered", "proxy": "probed", "frames": "proxied", "claude": "proxied"}

# Resting status for a share configured `index: false`: the local stages that
# matter are done (proxy, poster, sprite, transcript) and both the contact
# sheets and the model call were deliberately skipped. Deliberately NOT
# 'indexed' — that would claim segments and themes that do not exist — and
# deliberately not left at 'proxied', which would keep the clip in the work
# queue forever and make the watchdog respawn the run.
#
# RESTING, not terminal. `index: false` is a decision that can be revisited, so
# reopen_if_now_indexable() below puts these clips straight back into the queue
# the moment the flag is flipped. Without that, a share indexed later would sit
# here forever: nothing else in STAGE_PREREQ_STATUS accepts 'organised', so the
# clips would be invisible to every runner while looking finished.
ORGANISED_STATUS = "organised"


def skipped_for_length(video: dict[str, Any]) -> bool:
    """True for a clip stage_probe parked at 'skipped' for the duration cap.

    Told apart from the OTHER reason it parks one there structurally, not by
    re-reading the error prose: probe records a `codec` only when there is a
    video stream, so 'skipped' with a codec is the over-length clip and
    'skipped' without one is the audio-only clip — whose speech is still worth
    transcribing (see stage_probe). A row the scanner marked 'skipped' (an
    editor proxy folder) was never probed at all and has neither, which is why
    duration_s is checked too rather than just the absent codec.
    """
    return (
        video.get("status") == "skipped"
        and bool(video.get("codec"))
        and video.get("duration_s") is not None
    )


def reopen_if_now_indexable(cfg: Config, storage: Storage, video: dict[str, Any]) -> dict[str, Any]:
    """Put an `organised` clip back in the queue if its share is indexable again.

    Returns the video row, refreshed if it changed. Cheap and idempotent: for
    anything not resting in ORGANISED_STATUS it is a dict lookup and a return.

    'proxied' is the right landing spot because that is exactly where the clip
    stopped — the proxy exists, the contact sheets do not, and 'proxied' is the
    prerequisite for the frames stage that builds them.
    """
    if video["status"] != ORGANISED_STATUS:
        return video
    share_cfg = cfg.shares.get(video["share"])
    if share_cfg is None or not getattr(share_cfg, "index", True):
        return video
    storage.update_video(video["id"], status="proxied")
    logger.info("share %s is indexable again — reopening video %s for sheets "
                "and indexing", video["share"], video["id"])
    return storage.get_video(video["id"]) or video


DEFAULT_STAGES = tuple(STAGE_ORDER)


def stage_probe(cfg: Config, storage: Storage, video: dict[str, Any], src_path: Path) -> None:
    info = ffmpeg_tools.probe_video(src_path)

    # Audio-only file (yt-dlp sometimes fetches an audio stream into an .mp4):
    # a real duration but no video stream. There is nothing to see, so proxy,
    # sprite and frame extraction all fail — but the SPEECH is perfectly
    # indexable and its transcript stays searchable. Mark it done for visual
    # work rather than letting it error on every run.
    if not info.get("codec"):
        storage.update_video(
            video["id"], status="skipped",
            error="audio-only (no video stream) — transcript indexed, no visuals",
            **info,
        )
        logger.info("probe: video %s is audio-only, skipping visual stages", video["id"])
        return

    # Over-length gate, enforced HERE because probe is where duration first exists
    # and is still the cheapest stage — everything after it (proxy encode, scene
    # detection, frame extraction, model calls) is what a long take actually costs.
    # Left 'skipped' rather than 'excluded': an over-length clip is still real
    # footage of the shoot and still belongs in the copy manifest; it is only not
    # worth describing.
    share_cfg = cfg.shares.get(video["share"])
    cap = share_cfg.max_duration_s if share_cfg else None
    duration = info.get("duration_s")
    if cap is not None and duration is not None and duration > cap:
        storage.update_video(
            video["id"], status="skipped",
            error=f"longer than {cap:.0f}s cap ({duration:.0f}s) — not indexed",
            **info,
        )
        logger.info("probe: video %s is %.0fs, over the %.0fs cap — skipping",
                    video["id"], duration, cap)
        return

    storage.update_video(video["id"], status="probed", **info)


def stage_proxy(cfg: Config, storage: Storage, video: dict[str, Any], src_path: Path) -> None:
    proxies_dir = cfg.data_root / "proxies"
    sprites_dir = cfg.data_root / "sprites"
    posters_dir = cfg.data_root / "posters"
    for d in (proxies_dir, sprites_dir, posters_dir):
        d.mkdir(parents=True, exist_ok=True)

    duration_s = video["duration_s"]
    use_nvenc = ffmpeg_tools.detect_nvenc_available()

    proxy_path = proxies_dir / f"{video['id']}.mp4"
    ffmpeg_tools.build_proxy(src_path, proxy_path, use_nvenc=use_nvenc)

    # Sprite and poster come from the PROXY, not the original. Each is another
    # full decode pass, and with source media on a 46 MB/s network share those
    # reads dominate the whole run. The proxy is a faithful local copy and both
    # outputs are downscaled far below 540p anyway (240px sprite cells, 640px
    # poster), so nothing visible is lost. One network read per file instead of
    # three. Falls back to the original if the proxy is somehow missing.
    derived_src = proxy_path if proxy_path.is_file() and proxy_path.stat().st_size else src_path
    geometry = ffmpeg_tools.build_sprite(
        derived_src, sprites_dir / f"{video['id']}.jpg", duration_s=duration_s
    )
    ffmpeg_tools.build_poster(derived_src, posters_dir / f"{video['id']}.jpg", duration_s=duration_s)

    # Store the sheet's real geometry alongside the status (BROLL-1/BROLL-2,
    # 2026-08-11). The browser used to re-derive it from the SOURCE dimensions
    # and a flat model of this function's rules; both were wrong for most of the
    # archive, and neither is recoverable from the sheet after the fact.
    storage.update_video(video["id"], status="proxied", **geometry)


def _frames_source(cfg: Config, video: dict[str, Any], src_path: Path) -> Path:
    """Prefer the local proxy over the original for frame work.

    Scene detection decodes the whole file and frame extraction seeks all over
    it — two more full reads of the original, on top of the proxy encode. With
    source media on a 46 MB/s network share that dominates the entire run.

    The proxy is a faithful 540p copy on local disk, and contact-sheet cells are
    384px wide regardless of source, so the frames that reach the model are
    effectively identical. Falls back to the original when no proxy exists (e.g.
    `--stages frames` before `proxy`).
    """
    proxy = cfg.data_root / "proxies" / f"{video['id']}.mp4"
    if proxy.is_file() and proxy.stat().st_size > 0:
        return proxy
    return src_path


def stage_frames(cfg: Config, storage: Storage, video: dict[str, Any], src_path: Path) -> None:
    sheets_dir = cfg.data_root / "sheets" / str(video["id"])
    marker = sheets_dir / "_complete"
    if marker.exists():
        return  # idempotent: already extracted on a previous run

    sheets_dir.mkdir(parents=True, exist_ok=True)
    frames_src = _frames_source(cfg, video, src_path)
    timestamps = ffmpeg_tools.detect_scene_timestamps(frames_src, cfg.sampling.scene_threshold)
    timestamps = ffmpeg_tools.fill_gaps(timestamps, video["duration_s"], cfg.sampling.max_gap_s)
    frames = ffmpeg_tools.extract_frames(
        frames_src, timestamps, sheets_dir / "frames", duration_s=video["duration_s"]
    )
    if not frames:
        raise RuntimeError("no frames could be extracted — unreadable or truncated media")
    sheet_paths = ffmpeg_tools.build_contact_sheets(
        frames, sheets_dir, width=video.get("width"), height=video.get("height")
    )

    # Record the timestamps actually sampled, not the ones requested.
    (sheets_dir / "frames.json").write_text(
        json.dumps({"timestamps": [ts for ts, _ in frames], "sheets": [str(p) for p in sheet_paths]}),
        encoding="utf-8",
    )
    marker.write_text("ok", encoding="utf-8")


def _log_usage(
    cfg: Config, video: dict[str, Any], model: str, n_sheets: int, usage: dict[str, Any]
) -> None:
    """Append one line per model call to DATA_ROOT/usage.jsonl.

    This is how a real cost-per-clip-minute figure gets measured instead of
    estimated — the number needed to forecast a full archive run. Never let
    accounting break indexing.
    """
    if not usage:
        return
    try:
        record = {
            "video_id": video["id"],
            "rel_path": video.get("rel_path"),
            "duration_s": video.get("duration_s"),
            "model": model,
            "n_sheets": n_sheets,
            **usage,
        }
        path = cfg.data_root / "usage.jsonl"
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:
        pass


def stage_describe(
    cfg: Config, storage: Storage, video: dict[str, Any], model: str, invoke: InvokeFn = invoke_claude
) -> None:
    """Describe a clip's shots — dispatches on `cfg.indexer.backend`
    (2026-08-18, `broll/docs/local-indexing-options-2026-08-17.md` §3).

    `backend == "local"` runs Qwen3-VL through a vendored llama-server
    (local_vlm.describe_video) and returns; everything below this point is the
    ORIGINAL `stage_claude` body, byte-for-byte, for `backend == "anthropic"` —
    same prompt, same windowing, same retry, same usage log. `invoke` keeps its
    old meaning (and every existing Anthropic-path test its old fixture) only
    for that branch; the local branch does not take one; it plugs into
    llama-server through `local_vlm.call_local_with_retry` instead, at the
    same conceptual seam (see claude_client.InvokeFn's docstring for why this
    seam exists).
    """
    if cfg.indexer.backend == "local":
        local_vlm.describe_video(
            cfg, storage, video,
            log_usage=lambda m, n, u: _log_usage(cfg, video, m, n, u),
        )
        return

    sheets_dir = cfg.data_root / "sheets" / str(video["id"])
    meta_path = sheets_dir / "frames.json"
    if not meta_path.exists():
        raise RuntimeError("no contact sheets found — run the 'frames' stage first")

    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    sheet_paths = [Path(p) for p in meta["sheets"]]
    # Cap the sheets fed to the model before windowing. A long clip's sheets are
    # evenly subsampled to span its whole duration more coarsely, rather than
    # being sliced into many calls — see SamplingConfig.max_sheets_per_video.
    capped = cap_sheets(sheet_paths, cfg.sampling.max_sheets_per_video)
    if len(capped) < len(sheet_paths):
        logger.info("claude: video %s sheets capped %d -> %d",
                    video["id"], len(sheet_paths), len(capped))
    sheets_per_call = max(cfg.sampling.frames_per_call // 9, 1)
    windows = chunk_sheets(capped, sheets_per_call)

    taxonomy = [c["slug"] for c in storage.get_categories()]

    # The contact sheets travel WITH the request now, as base64 image blocks,
    # rather than being read off disk by a CLI whose working directory had to be
    # pinned to the sheets dir for its permission prompt. One SDK client for the
    # whole video, so its connection pool is reused across the windows; injected
    # mocks keep their (prompt, model) signature untouched.
    real_call = invoke is invoke_claude
    client = build_client(cfg.anthropic) if real_call else None

    results = []
    for window in windows:
        prompt = build_index_prompt(window, taxonomy)
        call = invoke
        if real_call:
            call = functools.partial(
                invoke_claude, images=window, settings=cfg.anthropic, client=client
            )
        result, usage = call_claude_with_retry(prompt, model, invoke=call)
        results.append(result)
        _log_usage(cfg, video, model, len(window), usage)

    merged = merge_index_results(results)
    storage.write_index_result(
        video["id"],
        themes=merged["themes"],
        quality_flags=merged["quality_flags"],
        category_hint=merged["category_hint"],
        segments=merged["segments"],
        model=resolve_model(model),
    )


def _find_existing_srt(out_dir: Path, src_path: Path) -> Path | None:
    """Locate an .srt already produced for `src_path` in `out_dir`, if any.

    A parallel batch transcription job (see docs/indexing-findings.md) writes
    DATA_ROOT/transcripts/{video_id}/{stem}.srt directly, ahead of and independent of
    this pipeline. Same stem-then-newest fallback as transcribe.run_whisper, in case the
    naming convention ever drifts.
    """
    if not out_dir.is_dir():
        return None
    candidate = out_dir / f"{src_path.stem}.srt"
    if candidate.is_file():
        return candidate
    candidates = sorted(out_dir.glob("*.srt"), key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0] if candidates else None


def stage_transcribe(
    cfg: Config,
    storage: Storage,
    video: dict[str, Any],
    src_path: Path,
    runner=transcribe.run_whisper,
    ingest_only: bool = False,
) -> None:
    """Local speech transcription (faster-whisper) — additive enrichment only.

    Deliberately independent of the visual pipeline's discovered -> probed -> proxied ->
    indexed status flow: never sets videos.status, never gates the claude stage, and a
    failure here (missing audio, whisper unavailable, a bad clip) is logged and swallowed
    rather than raised — see docs/indexing-findings.md. A clip with no useful audio is
    still a perfectly good indexed clip.

    Idempotent: skips if videos.transcribed_at is already set, and reuses an existing
    .srt under DATA_ROOT/transcripts/{id}/ instead of re-running whisper — a batch
    transcription job may already have produced one.

    `ingest_only=True` means: use an existing .srt or do nothing. Without it, a
    caller that expected the cheap ingest path silently gets a full Whisper run
    whenever the .srt is absent — which is exactly what happens on a share that
    has never been through batch_transcribe.py. Measured on the FF4 share: six
    workers at 100% CPU and 2.3 GB each, zero videos probed in twelve minutes,
    and because this stage runs BEFORE stage_probe it was transcribing the
    multi-hour interview takes that max_duration_s was about to discard.
    """
    if video.get("transcribed_at"):
        return

    if not cfg.whisper.enabled:
        logger.info("transcribe: video %s skipped (whisper.enabled is false)", video["id"])
        return

    out_dir = cfg.data_root / "transcripts" / str(video["id"])

    try:
        existing = _find_existing_srt(out_dir, src_path)
        if existing is not None:
            cues = transcribe.merge_cues(
                transcribe.parse_srt(existing.read_text(encoding="utf-8", errors="replace")),
                max_gap_s=cfg.whisper.max_gap_s,
                max_duration_s=cfg.whisper.max_duration_s,
            )
        elif ingest_only:
            logger.info(
                "transcribe: video %s skipped (no .srt yet, ingest_only)", video["id"]
            )
            return
        else:
            if not cfg.whisper.python or not cfg.whisper.script:
                # Unconfigured is not an error HERE — this stage is additive
                # enrichment and must never fail a video — but it is the state a
                # fresh install is in, so the message names the keys rather than
                # saying "not found: . / ." (2026-08-17, item 14). The stage the
                # operator asked for by name refuses instead: Config.require_whisper.
                logger.info(
                    "transcribe: video %s skipped (whisper.python/whisper.script not "
                    "configured — see docs/INDEXERS.md, or set CCSYNC_WHISPER_PYTHON "
                    "/ CCSYNC_WHISPER_SCRIPT)", video["id"],
                )
                return
            python_exe = Path(cfg.whisper.python)
            script_path = Path(cfg.whisper.script)
            if not python_exe.is_file() or not script_path.is_file():
                logger.info(
                    "transcribe: video %s skipped (whisper python/script not found: %s / %s)",
                    video["id"], python_exe, script_path,
                )
                return
            cues = transcribe.transcribe_file(
                src_path, out_dir,
                str(python_exe), str(script_path),
                model=cfg.whisper.model,
                model_dir=cfg.whisper.model_dir,
                language=cfg.whisper.language,
                max_gap_s=cfg.whisper.max_gap_s,
                max_duration_s=cfg.whisper.max_duration_s,
                runner=runner,
            )
        # Quality gate before anything reaches the index. Whisper fed near-silence
        # invents plausible text — the 38-min dashcam in this corpus produced a
        # repeated subtitle-credit line naming a singer who is nowhere in the
        # footage. A confidently wrong hit is worse than no hit, so a transcript
        # that fails assessment is discarded rather than stored.
        cues = [
            c for c in cues
            if not transcript_quality.contains_known_artifact(c.text)
        ]
        verdict = transcript_quality.assess(
            [c.text for c in cues], duration_s=video.get("duration_s")
        )
        if not verdict:
            logger.info(
                "transcribe: video %s transcript rejected (%s)", video["id"], verdict.reason
            )
            # Mark it attempted so we don't re-transcribe silent footage every run,
            # but store no cues.
            storage.write_transcript(video["id"], [], cfg.whisper.language)
            return

        storage.write_transcript(video["id"], cues, cfg.whisper.language)
    except Exception as e:  # noqa: BLE001 - additive enrichment, must never fail the video
        logger.warning("transcribe: video %s failed: %s", video["id"], e)


def _segment_search_text(seg: dict[str, Any]) -> str:
    """Concatenate a segment's searchable fields for both search_norm and embedding
    input, per SPEC.md's Claude indexing output contract."""
    parts = [
        seg.get("description") or "",
        seg.get("objects") or "",
        seg.get("setting") or "",
        seg.get("onscreen_text") or "",
        seg.get("onscreen_text_en") or "",
    ]
    return " ".join(p for p in parts if p)


def stage_embed(cfg: Config, storage: Storage, video: dict[str, Any]) -> None:
    """Hybrid search enrichment: CJK keyword normalization + semantic embeddings.

    Additive enrichment, same shape as stage_transcribe: status-independent (never sets
    videos.status), never blocks another stage, and every failure is logged and
    swallowed rather than raised — a machine without jieba/opencc/fastembed installed,
    or a DB not yet migrated to v4 (see migrate.py, migrations/004_hybrid_search.sql),
    still indexes clips fine, just without this enrichment. See broll_index/normalize.py
    and broll_index/embed.py for the two independent mechanisms this computes.

    Idempotent: a row is skipped entirely once it already has both a non-empty
    search_norm and an embeddings row for the currently configured model. A model
    change in cfg.embedding.model re-embeds rows (but search_norm, which doesn't depend
    on the embedding model, is not recomputed once already populated).
    """
    if not cfg.embedding.enabled:
        logger.info("embed: video %s skipped (embedding.enabled is false)", video["id"])
        return

    model_name = cfg.embedding.model
    try:
        segments = storage.get_segments(video["id"])
        transcripts = storage.get_transcript_segments(video["id"])
        existing_models = storage.get_embedding_models(video["id"])

        to_embed: list[tuple[str, int, str]] = []  # (source, source_id, text)
        # Accumulated and written once per video (BROLL-IDX-8, 2026-08-14): the
        # per-row calls each committed their own transaction and bumped the
        # single `meta` search-generation row, which for a full re-embed of this
        # corpus is ~83,000 fsyncs where ~7,100 do the same job — and made that
        # one row a hot spot every concurrent writer contends on.
        norms: list[tuple[str, int, str]] = []  # (source, source_id, search_norm)

        for seg in segments:
            text = _segment_search_text(seg)
            if not seg.get("search_norm"):
                norms.append(("segment", seg["id"], normalize.searchable_blob(text)))
            if text.strip() and existing_models.get(("segment", seg["id"])) != model_name:
                to_embed.append(("segment", seg["id"], text))

        for cue in transcripts:
            text = cue.get("text") or ""
            if not cue.get("search_norm"):
                norms.append(("transcript", cue["id"], normalize.searchable_blob(text)))
            if text.strip() and existing_models.get(("transcript", cue["id"])) != model_name:
                to_embed.append(("transcript", cue["id"], text))

        # Flushed before the embedding work and before the early returns below:
        # normalization is useful on its own (it is what keyword search reads),
        # and a machine without fastembed must still get it.
        storage.update_search_norms(norms)

        if not to_embed:
            return
        if not embed.fastembed_available():
            logger.info("embed: video %s skipped embedding (fastembed not installed)", video["id"])
            return

        texts = [t for _, _, t in to_embed]
        vectors = embed.embed_texts(texts, model_name=model_name,
                                    batch_size=cfg.embedding.batch_size,
                                    cache_dir=cfg.embedding.cache_dir)
        dim = int(vectors.shape[1]) if vectors.size else 0
        storage.upsert_embeddings([
            (source, source_id, video["id"], model_name, dim, embed.to_blob(vec))
            for (source, source_id, _text), vec in zip(to_embed, vectors)
        ])
    except Exception as e:  # noqa: BLE001 - additive enrichment, must never fail the video
        logger.warning("embed: video %s failed: %s", video["id"], e)


def _process_video(
    cfg: Config,
    storage: Storage,
    video: dict[str, Any],
    *,
    model: str,
    requested_stages: set[str],
    invoke: InvokeFn = invoke_claude,
) -> None:
    # Before anything else: a clip resting at 'organised' whose share has since
    # been switched back to index:true rejoins the queue here.
    current = reopen_if_now_indexable(cfg, storage, video)
    for stage in STAGE_ORDER:
        if stage not in requested_stages:
            continue
        # "transcribe"/"embed" have no entry in STAGE_PREREQ_STATUS on purpose (see the
        # comment by STAGE_ORDER): both always proceed, independent of the video's
        # current status.
        if stage in STAGE_PREREQ_STATUS and current["status"] != STAGE_PREREQ_STATUS[stage]:
            continue

        # A share configured `index: false` gets no model call — and no contact
        # sheets either, because sheets exist for exactly one purpose: to be the
        # images sent to the model. Building them anyway means a full scene-
        # detection decode of every clip to produce JPEGs nothing will ever
        # read, which on the MOFA shoot is 554 clips of the single most
        # expensive local stage.
        #
        # Enforced HERE, at the last possible moment, rather than only by
        # filtering the work queue: this is the one place every path into these
        # stages passes through, so a caller that hand-picks video ids still
        # cannot spend money — or an evening of CPU — on a share that opted out.
        # No usable speech on our own b-roll: cutaways with incidental crew
        # chatter, so transcribing produces cues that are noise in the index.
        if stage == "transcribe":
            sc = cfg.shares.get(current["share"])
            if sc is not None and not getattr(sc, "transcribe", True):
                continue
            # `transcribe` has no STAGE_PREREQ_STATUS entry, so it runs whatever
            # the row's status is — including the 'skipped' stage_probe set two
            # stages ago for a clip over max_duration_s. That is the exact waste
            # the cap exists to avoid: a 3-hour A-cam take probed, discarded, and
            # then transcribed end to end anyway (BROLL-4, 2026-08-11;
            # parallel_local.py was fixed for this, the serial path was not).
            # Audio-only 'skipped' clips still transcribe — their speech is the
            # only index they will ever have.
            if skipped_for_length(current):
                logger.info(
                    "transcribe: video %s skipped (over the duration cap — %s)",
                    current["id"], current.get("error"),
                )
                continue

        if stage in ("frames", "claude"):
            share_cfg = cfg.shares.get(current["share"])
            # getattr, not attribute access: opting out is the exception, so an
            # unknown or stubbed share config must fall through to the normal
            # indexed path rather than silently skipping the paid stage.
            if share_cfg is not None and not getattr(share_cfg, "index", True):
                if current["status"] != ORGANISED_STATUS:
                    storage.update_video(current["id"], status=ORGANISED_STATUS)
                    logger.info("share %s is index:false — video %s organised after the "
                                "proxy; no contact sheets, no model call",
                                current["share"], current["id"])
                    refreshed = storage.get_video(current["id"])
                    if refreshed is not None:
                        current = refreshed
                # `continue`, not `return` (BROLL-5, 2026-08-11): returning here
                # abandoned the loop at `frames`, which sits BEFORE `transcribe`
                # in STAGE_ORDER — so `index: false` silently implied
                # `transcribe: false` however the share was configured, and
                # `embed` never ran either. The remaining status-gated stages
                # decline on their own now that the row reads 'organised'
                # (claude wants 'proxied'), which is what makes this safe.
                continue

        if stage == "embed":
            # No src_path needed (embed only reads/writes already-stored segments and
            # transcript rows) — resolved independently of share config validity so an
            # unknown/misconfigured share can never turn into an 'error' status for
            # this stage, matching stage_embed's status-independent guarantee.
            try:
                stage_embed(cfg, storage, current)
            except Exception as e:  # noqa: BLE001 - belt-and-suspenders, see stage_transcribe's note below
                logger.warning("embed: video %s failed: %s", current["id"], e)
            refreshed = storage.get_video(current["id"])
            if refreshed is None:
                return
            current = refreshed
            continue

        share_cfg = cfg.shares.get(current["share"])
        if share_cfg is None:
            storage.set_error(current["id"], f"unknown share '{current['share']}' (not in config)")
            return
        src_path = Path(share_cfg.root) / current["rel_path"]

        try:
            if stage == "probe":
                stage_probe(cfg, storage, current, src_path)
            elif stage == "proxy":
                stage_proxy(cfg, storage, current, src_path)
            elif stage == "frames":
                stage_frames(cfg, storage, current, src_path)
            elif stage == "transcribe":
                # ingest_only: use an .srt batch_transcribe.py already wrote, or
                # do nothing. Without it this stage quietly runs Whisper itself
                # on any share that has never been through the batch job — six
                # saturated CPU workers ahead of every other stage, measured on
                # FF4 (BROLL-4, 2026-08-11). parallel_local.py has passed this
                # since that measurement; the serial path had not.
                stage_transcribe(cfg, storage, current, src_path, ingest_only=True)
            elif stage == "claude":
                stage_describe(cfg, storage, current, model, invoke=invoke)
        except Exception as e:  # noqa: BLE001 - a stage failure must never crash the queue
            if stage == "transcribe":
                # Belt-and-suspenders: stage_transcribe already catches and logs its own
                # failures internally (so this branch shouldn't normally trigger), but
                # transcription is additive enrichment and must never error the video out
                # or block a later stage (e.g. claude) even if that inner guard is bypassed
                # (a monkeypatched stage_transcribe in tests, for instance).
                logger.warning("transcribe: video %s failed: %s", current["id"], e)
            # Match on the MESSAGE, not the exception class. A rate limit used
            # to arrive two different ways from the `claude -p` CLI — as
            # ClaudeCallError when it exited 0 but reported is_error in its
            # envelope, and as a plain RuntimeError when it exited non-zero. An
            # earlier version required ClaudeCallError here, so a 429 delivered
            # by non-zero exit slipped through and marked 1,097 videos 'error'
            # in a single night — precisely what FatalRunError exists to
            # prevent. The SDK is tidier (ClaudeCallError, always), but the rule
            # stands: classify on what the failure SAYS, so a new transport
            # cannot reintroduce that night.
            #
            # Gated on the stage that actually calls the API (BROLL-IDX-1,
            # 2026-08-14): probe/proxy/frames failures carry filenames and whole
            # ffmpeg argvs, so their text routinely contains API-ish substrings
            # that have nothing to do with the account. Classifying one of those
            # as account-wide aborted the run AND left the clip runnable, so
            # every re-run stopped on the same clip forever.
            elif stage == "claude" and (
                is_fatal_api_error(str(e))
                # Same account-wide-vs-per-video distinction, for the local
                # backend: a dead/refused llama-server will fail every
                # remaining clip identically (unlike a per-clip parse
                # failure, which is not fatal — see local_vlm.LocalVlmError's
                # docstring), so it gets the same "stop, don't mark 'error'"
                # treatment rather than marching through the queue.
                or (cfg.indexer.backend == "local" and local_vlm.is_fatal_local_error(str(e)))
            ):
                # Environmental, not per-video: exhausted credit, bad auth, and the
                # like will fail every remaining call identically. Marking each video
                # 'error' would march through the archive destroying the queue's
                # resumability for a problem that has nothing to do with the footage.
                # Leave this video's status untouched and abort the run.
                raise FatalRunError(str(e)) from e
            else:
                storage.set_error(current["id"], f"{stage} failed: {e}")
                return

        refreshed = storage.get_video(current["id"])
        if refreshed is None:
            return
        current = refreshed


def run_pipeline(
    cfg: Config,
    storage: Storage,
    *,
    model: str | None = None,
    limit: int | None = None,
    stages: list[str] | None = None,
    invoke: InvokeFn = invoke_claude,
) -> int:
    """Drain the job queue. Returns the number of videos processed (attempted) this run."""
    requested_stages = set(stages) if stages else set(DEFAULT_STAGES)
    resolved_model = model or cfg.model

    # ORGANISED_STATUS is in the work list even though no stage claims it as a
    # prerequisite (BROLL-IDX-4, 2026-08-14): it is a RESTING status, and
    # _process_video's reopen_if_now_indexable is what puts those clips back in
    # the queue when a share's `index: false` is revisited. Without it that call
    # was unreachable from the CLI — `broll-index run` printed "processed 0
    # video(s)" on a re-enabled share whose clips were all sitting at
    # 'organised', and only parallel_local.eligible_ids (which has always
    # included it) could see them. A row whose share is still opted out costs a
    # dict lookup and is declined by every status-gated stage.
    statuses = ["discovered", "probed", "proxied", ORGANISED_STATUS]
    if "transcribe" in requested_stages or "embed" in requested_stages:
        # Both are status-independent additive enrichment, so already-finished videos
        # are still eligible — otherwise an archive indexed before these stages existed
        # could never pick up its transcripts / search_norm / embeddings.
        statuses += ["indexed", "sorted"]
    # storage.videos_by_status excludes confirmed duplicates (duplicate_of IS NOT NULL)
    # at the query level — see broll_index/duplicates.py. A known duplicate of another
    # indexed row must never spend a model call describing footage already described.
    # Record where each share's footage lives before doing any work. Best
    # effort and never fatal — see share_push.push_shares.
    push_shares(cfg, storage)

    videos = storage.videos_by_status(statuses, limit=limit)
    count = 0
    for video in videos:
        if limit is not None and count >= limit:
            break
        try:
            _process_video(
                cfg, storage, video, model=resolved_model,
                requested_stages=requested_stages, invoke=invoke,
            )
        except FatalRunError as e:
            # Stop cleanly rather than failing every remaining video against a
            # problem that is not theirs. Everything already done is kept, and the
            # queue resumes from here once the cause is fixed.
            msg = str(e)
            if is_rate_limited(msg):
                reset = extract_reset_hint(msg)
                logger.error(
                    "rate limit reached after %d video(s) this run%s. "
                    "The queue is untouched — re-run to pick up where it stopped. (%s)",
                    count,
                    f"; resets {reset}" if reset else "",
                    msg,
                )
            else:
                logger.error(
                    "aborting run after %d video(s): %s. The queue is unchanged — "
                    "fix the cause and re-run to resume.", count, msg,
                )
            raise
        count += 1
    return count
