"""Config loading for indexer/config.yaml (see config.example.yaml for the shape)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class ShareConfig:
    root: str
    description: str = ""
    # "originals" (default) — the YouTube-archive shape: the camera/download file
    # IS the archive copy, and an editor's Proxy/ folder beside it is a redundant
    # second encode to be skipped.
    #
    # "proxies" — our own shot footage: the Proxy/ .mov IS what gets archived and
    # copied to the server, and the camera original is 20x its size and stays on
    # the shoot drive. Measured on the MOFA event: 558 proxies at 17.6 GB against
    # 558 originals at 403 GB. Same two files on disk, opposite verdicts, which is
    # why this is per-share and not a global rule.
    source: str = "originals"
    # Ignore clips longer than this many seconds. Long takes are interviews and
    # locked-off recordings rather than b-roll, and they dominate a run's cost:
    # on the MOFA event 4 of 558 clips (0.7%) are 16% of the total runtime.
    # None (default) means no cap, so existing shares are untouched.
    max_duration_s: float | None = None
    # Directory patterns, relative to `root`, never to be walked.
    #
    # A project folder is not homogeneous: FF4 holds our own shot footage, the
    # YouTube downloads that already have their own `originals` shares, and After
    # Effects comps, all under one tree. Without this the only way to avoid the
    # download folders was to root a share at each shot-footage folder instead —
    # which works, but flattens the structure, because build_archive files a
    # proxies-share clip at `Creators_Club/<share>/<rel_path>`. The share root IS
    # the top of what an editor sees, so it has to be the project.
    #
    # The cost of getting this wrong is asymmetric: a missing exclude indexes the
    # editor proxy of a download already indexed from its original — two search
    # hits for one clip, which content hashing cannot catch (same footage,
    # different encode, different bytes). That is the same double-count
    # PROXY_DIR_RE exists to prevent.
    #
    # Patterns are fnmatch against each directory's forward-slash path relative
    # to the root, so `*` DOES cross separators: "*/AE" also matches
    # "Nuclear/B-roll/AE". Matching a directory prunes its whole subtree.
    exclude: list[str] = field(default_factory=list)
    # False = do every LOCAL stage but never spend a model call on this share.
    #
    # Our own shoots do not need describing to be usable: we know what we shot,
    # and the folder tree (project / day / camera) already organises them the
    # way an editor looks for them. The local stages still run, so the clips are
    # browsable (poster, sprite), previewable (proxy) and searchable by speech
    # (Whisper is local and free) — everything except the paid layer.
    index: bool = True
    # False = never run speech transcription on this share.
    #
    # Our own b-roll has no usable speech: it is cutaways and atmosphere with
    # incidental crew chatter over the top. Transcribing it costs GPU time to
    # produce cues that are noise in the search index -- actively worse than
    # nothing, because a query can match a grip saying "is it rolling".
    transcribe: bool = True


@dataclass
class DbConfig:
    mode: str  # "sqlite" | "api"
    path: str | None = None
    url: str | None = None
    token: str | None = None


@dataclass
class SamplingConfig:
    scene_threshold: float = 0.3
    max_gap_s: float = 4.0
    frames_per_call: int = 36
    # Upper bound on contact sheets fed to the model per video. A long clip with
    # many scene cuts produces dozens of sheets and is sliced into as many as 17
    # model calls; measured on the real archive, 9% of videos (the long tail)
    # consumed 36% of ALL calls this way, and each call re-pays both the image
    # cost and the per-segment output cost. Capping evenly subsamples the sheets
    # so a long clip still spans its whole duration, just more coarsely. 0 or
    # negative disables the cap (the pre-cap behaviour). Applied at the claude
    # stage, so it needs no re-run of the frames stage.
    max_sheets_per_video: int = 0


@dataclass
class EmbeddingConfig:
    """Semantic embeddings (see broll_index/embed.py, docs/indexing-findings.md).

    Additive enrichment like whisper transcription: computed by the `embed` pipeline
    stage, status-independent, never blocks or errors a video. `model` is recorded per
    row in the `embeddings` table (migrations/004_hybrid_search.sql) so changing it here
    triggers re-embedding rather than silently comparing incompatible vector spaces.
    """
    enabled: bool = True
    model: str = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    batch_size: int = 64


@dataclass
class WhisperConfig:
    """Local speech transcription (see broll_index/transcribe.py, docs/indexing-findings.md).

    Shells out to an existing faster-whisper environment rather than importing it, because
    that environment already has working CUDA/cuDNN DLL wiring on Windows. `language=None`
    means autodetect (whisper's default); set it to force a language (e.g. "zh").
    """
    enabled: bool = True
    python: str = r"C:\Users\alex\tools\whisper\.venv\Scripts\python.exe"
    script: str = r"C:\Users\alex\tools\whisper\transcribe.py"
    model: str = "large-v3-turbo"
    language: str | None = None
    max_gap_s: float = 1.0
    max_duration_s: float = 30.0


@dataclass
class Config:
    shares: dict[str, ShareConfig]
    data_root: Path
    db: DbConfig
    model: str = "sonnet"
    taxonomy_model: str = "sonnet"
    # Index against the Claude Code subscription rather than pay-as-you-go API
    # credit. ANTHROPIC_API_KEY silently takes precedence over the claude.ai login
    # wherever it is set, so when true the key is dropped for the `claude`
    # subprocess only (the parent environment is left alone).
    use_subscription: bool = True
    sampling: SamplingConfig = field(default_factory=SamplingConfig)
    whisper: WhisperConfig = field(default_factory=WhisperConfig)
    embedding: EmbeddingConfig = field(default_factory=EmbeddingConfig)

    @property
    def local_state_db_path(self) -> Path:
        """Shadow sqlite db the indexer keeps for its own queue bookkeeping in `api` mode.

        See broll_index/storage/http_backend.py for why this exists — the ingest API
        contract in SPEC.md has no "list videos by status" endpoint, so the indexer needs
        somewhere local to track queue state when it isn't co-located with the web DB.
        """
        return self.data_root / "indexer_local_state.db"


VALID_SHARE_SOURCES = ("originals", "proxies")


def _build_shares(raw: dict[str, Any]) -> dict[str, ShareConfig]:
    shares = {}
    for name, entry in (raw or {}).items():
        if isinstance(entry, str):
            shares[name] = ShareConfig(root=entry)
            continue
        source = entry.get("source", "originals")
        if source not in VALID_SHARE_SOURCES:
            # Fail loudly rather than defaulting: a typo here silently indexes the
            # wrong side of a proxy pair, which costs a full run to discover.
            raise ValueError(
                f"share {name!r}: source must be one of "
                f"{', '.join(VALID_SHARE_SOURCES)}, got {source!r}"
            )
        max_dur = entry.get("max_duration_s")
        exclude = entry.get("exclude") or []
        if isinstance(exclude, str):
            # A bare string is silently iterable as characters, which would
            # exclude nothing and look like it worked. Reject it.
            raise ValueError(f"share {name!r}: exclude must be a list, not a string")
        shares[name] = ShareConfig(
            root=entry["root"],
            description=entry.get("description", ""),
            source=source,
            max_duration_s=float(max_dur) if max_dur is not None else None,
            exclude=[str(p).strip("/") for p in exclude],
            index=bool(entry.get("index", True)),
            transcribe=bool(entry.get("transcribe", True)),
        )
    return shares


def load_config(path: str | Path) -> Config:
    path = Path(path)
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}

    db_raw = raw.get("db") or {}
    db = DbConfig(
        mode=db_raw.get("mode", "sqlite"),
        path=db_raw.get("path"),
        url=db_raw.get("url"),
        token=db_raw.get("token"),
    )

    sampling_raw = raw.get("sampling") or {}
    sampling = SamplingConfig(
        scene_threshold=float(sampling_raw.get("scene_threshold", 0.3)),
        max_gap_s=float(sampling_raw.get("max_gap_s", 4.0)),
        frames_per_call=int(sampling_raw.get("frames_per_call", 36)),
        max_sheets_per_video=int(sampling_raw.get("max_sheets_per_video", 0)),
    )

    whisper_raw = raw.get("whisper") or {}
    whisper_defaults = WhisperConfig()
    whisper = WhisperConfig(
        enabled=bool(whisper_raw.get("enabled", whisper_defaults.enabled)),
        python=whisper_raw.get("python", whisper_defaults.python),
        script=whisper_raw.get("script", whisper_defaults.script),
        model=whisper_raw.get("model", whisper_defaults.model),
        language=whisper_raw.get("language", whisper_defaults.language),
        max_gap_s=float(whisper_raw.get("max_gap_s", whisper_defaults.max_gap_s)),
        max_duration_s=float(whisper_raw.get("max_duration_s", whisper_defaults.max_duration_s)),
    )

    embedding_raw = raw.get("embedding") or {}
    embedding_defaults = EmbeddingConfig()
    embedding = EmbeddingConfig(
        enabled=bool(embedding_raw.get("enabled", embedding_defaults.enabled)),
        model=embedding_raw.get("model", embedding_defaults.model),
        batch_size=int(embedding_raw.get("batch_size", embedding_defaults.batch_size)),
    )

    return Config(
        shares=_build_shares(raw.get("shares") or {}),
        data_root=Path(raw["data_root"]),
        db=db,
        model=raw.get("model", "sonnet"),
        taxonomy_model=raw.get("taxonomy_model", "sonnet"),
        use_subscription=bool(raw.get("use_subscription", True)),
        sampling=sampling,
        whisper=whisper,
        embedding=embedding,
    )
