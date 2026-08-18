"""Config loading for indexer/config.yaml (see config.example.yaml for the shape)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import os

import yaml


class ConfigError(ValueError):
    """A required setting is absent or unusable. The message NAMES the key.

    2026-08-17, COMMERCIAL_READINESS.md item 14. The paths this indexer needs
    (`data_root`, `db.path`, the whisper environment, the model caches) used to
    default to one workstation's directories, so a customer's first run either
    wrote somewhere surprising or failed with a KeyError naming nothing. Every
    one of them is now required, and every refusal says which key and which
    environment variable would supply it.
    """


def _env(*names: str) -> str | None:
    """First non-empty environment variable in `names`, else None."""
    for name in names:
        value = (os.environ.get(name) or "").strip()
        if value:
            return value
    return None


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
    # Where fastembed keeps downloaded ONNX weights. Empty = its own default
    # (~/.cache/fastembed), which inside a container is a layer that is thrown
    # away on every run — so the GPU image mounts a volume and points this at it
    # (2026-08-17, COMMERCIAL_READINESS.md item 14).
    cache_dir: str = ""


@dataclass
class WhisperConfig:
    """Local speech transcription (see broll_index/transcribe.py, docs/indexing-findings.md).

    Shells out to a faster-whisper environment rather than importing it, because that
    environment needs working CUDA/cuDNN DLL wiring on Windows which is painful to
    reproduce in-process. `language=None` means autodetect (whisper's default); set it
    to force a language (e.g. "zh").

    2026-08-17, COMMERCIAL_READINESS.md item 14: `python`/`script` have NO default.
    They used to point at one operator's `C:\\Users\\...\\tools\\whisper`, which no
    customer has and which the repo could not reproduce — the environment "wasn't in
    this repo". It is now: `tools/make_whisper_env.ps1` / `.sh` build a pinned sidecar
    venv and `tools/whisper_transcribe.py` is the helper it runs. Empty means "not
    configured"; `Config.require_whisper()` refuses by name rather than shelling out
    to nothing. `model_dir` is the model cache (faster-whisper downloads large-v3-turbo
    on first use); unset means the child process's own HuggingFace default, which on a
    container is a throwaway layer.
    """
    enabled: bool = True
    python: str = ""
    script: str = ""
    model: str = "large-v3-turbo"
    model_dir: str = ""
    language: str | None = None
    max_gap_s: float = 1.0
    max_duration_s: float = 30.0


@dataclass
class AnthropicConfig:
    """How the indexer reaches the Anthropic Messages API.

    2026-08-17, COMMERCIAL_READINESS.md item 1: replaces `use_subscription`. The
    indexer used to drive the `claude -p` CLI against the operator's personal
    Claude Code subscription; a customer install calls the API with its own key.

    THE KEY ITSELF IS NEVER IN THIS FILE. config.yaml is copied between machines,
    pasted into support threads and committed to repos. `api_key_env` names the
    environment variable to read; `api_key_file` points at a file holding it.
    """
    api_key_env: str = "ANTHROPIC_API_KEY"
    api_key_file: str | None = None
    # Contact-sheet descriptions run ~2-4k output tokens for a busy window; 8k
    # leaves room for a long clip's segment list without inviting a runaway.
    max_tokens: int = 8000
    timeout_s: float = 600.0
    # Retries are per call, on 429/5xx/overloaded only (broll_index.claude_client).
    # Past this the failure is reported as account-wide so the run stops with the
    # queue resumable rather than marking every remaining clip 'error'.
    max_retries: int = 5
    retry_base_delay_s: float = 2.0
    retry_max_delay_s: float = 60.0
    # Ceiling on API calls in flight, enforced inside the client. The stage is
    # latency-bound (~84 s/call measured), so this is the throughput knob;
    # parallel_claude.py's --workers sets it for a run.
    max_concurrency: int = 4
    # "disabled" | "adaptive". Indexing a contact sheet is extraction, not
    # reasoning, and thinking tokens are billed on every one of tens of
    # thousands of calls — so off by default, and available for an archive where
    # the descriptions justify it.
    thinking: str = "disabled"


@dataclass
class IndexerConfig:
    """Which vision backend describes a clip's shots — 2026-08-18, the
    "local by default" decision (`broll/docs/local-indexing-options-2026-08-17.md`
    §3, proven out by `broll/eval/local_vlm/results/report.md`).

    `backend`: "local" runs Qwen3-VL through a vendored llama.cpp (see
    `local_models.py`/`local_runtime.py`/`local_vlm.py`) — zero marginal cost,
    needs a GPU. "anthropic" is the original Messages API path
    (`claude_client.py`), unchanged, for a site that wants the better first
    impression `broll/docs/indexing-api.md` describes, or has no GPU to spare.

    `model_tier`: "good" (Qwen3-VL-4B, 8 GB VRAM) or "best" (Qwen3-VL-8B,
    12 GB VRAM) — see `local_models.TIERS`. `model_tier_explicit` is set by
    `load_config` when `model_tier` was actually written in config.yaml, which
    is what lets `dashboard_site.resolve_model_tier` tell "the operator chose
    this" from "nobody said, ask the dashboard manifest, then default good".

    `local_cache_dir`: where the runtime binary and GGUF weights land — "" means
    `local_runtime.default_cache_dir()` (per-OS: see that function). This is
    NOT `data_root`: those tens of GB are the archive's own frames/proxies and
    get backed up per-site; the model cache is the same handful of GB on every
    machine of the same tier and is never site data.

    `llama_server_path`: point at an already-installed `llama-server` instead
    of the vendored download (e.g. a distro package, or a hand-built server).
    "" = fetched into `local_cache_dir` by `local_runtime.ensure_runtime`.

    `dashboard_url`: explicit override for where to ask
    `GET /api/v1/site` for `indexer.model_tier` when config.yaml does not say
    (see `dashboard_site.py`). "" = derive it from `db.url` when
    `db.mode == "api"`, else no manifest lookup.
    """
    backend: str = "local"
    model_tier: str = "good"
    model_tier_explicit: bool = False
    local_cache_dir: str = ""
    llama_server_path: str = ""
    dashboard_url: str = ""
    # Frames per llama-server call (9 = one 3x3 sheet's worth of images, but
    # sent as individual native-resolution frames, not a tiled sheet — see
    # local_vlm.py). gpu_layers is llama.cpp's `-ngl`; 99 offloads every layer
    # it can, the same flag the eval ran with (b10470, `-ngl 99`).
    frames_per_call: int = 9
    gpu_layers: int = 99
    # The eval's remaining known gap (results/report.md: 10.3 segments/clip
    # predicted vs Haiku's 4.3) — merge adjacent over-segmented shots back
    # together (local_vlm.merge_similar_segments). Local only by default:
    # Claude's segments were already close to per-shot, so there is nothing to
    # merge there and turning it on would just risk collapsing two real cuts
    # that happen to look similar.
    merge_similar_segments: bool = True


@dataclass
class Config:
    shares: dict[str, ShareConfig]
    data_root: Path
    db: DbConfig
    model: str = "sonnet"
    taxonomy_model: str = "sonnet"
    anthropic: AnthropicConfig = field(default_factory=AnthropicConfig)
    sampling: SamplingConfig = field(default_factory=SamplingConfig)
    whisper: WhisperConfig = field(default_factory=WhisperConfig)
    embedding: EmbeddingConfig = field(default_factory=EmbeddingConfig)
    indexer: IndexerConfig = field(default_factory=IndexerConfig)

    @property
    def local_state_db_path(self) -> Path:
        """Shadow sqlite db the indexer keeps for its own queue bookkeeping in `api` mode.

        See broll_index/storage/http_backend.py for why this exists — the ingest API
        contract in SPEC.md has no "list videos by status" endpoint, so the indexer needs
        somewhere local to track queue state when it isn't co-located with the web DB.
        """
        return self.data_root / "indexer_local_state.db"

    def require_whisper(self) -> tuple[Path, Path]:
        """(python, script) for the transcription helper, or raise by name.

        The `transcribe` stage is additive enrichment and skips quietly when this
        is unconfigured (broll_index/pipeline.py) — but a run the operator asked
        for BY NAME (`broll-index transcribe`, batch_transcribe.py) must say what
        is missing instead of reporting "0 transcribed". 2026-08-17,
        COMMERCIAL_READINESS.md item 14.
        """
        missing = [
            key for key, value, env in (
                ("whisper.python", self.whisper.python, "CCSYNC_WHISPER_PYTHON"),
                ("whisper.script", self.whisper.script, "CCSYNC_WHISPER_SCRIPT"),
            ) if not value
        ]
        if missing:
            raise ConfigError(
                f"{' and '.join(missing)} is not set. Transcription shells out to a "
                "faster-whisper environment: build one with "
                "broll/indexer/tools/make_whisper_env.ps1 (or .sh) and set the keys "
                "in config.yaml, or export CCSYNC_WHISPER_PYTHON / "
                "CCSYNC_WHISPER_SCRIPT. See docs/INDEXERS.md."
            )
        python, script = Path(self.whisper.python), Path(self.whisper.script)
        for key, path in (("whisper.python", python), ("whisper.script", script)):
            if not path.is_file():
                raise ConfigError(f"{key} points at {path}, which is not a file")
        return python, script


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


def _build_anthropic(raw: dict[str, Any]) -> AnthropicConfig:
    d = AnthropicConfig()
    # A key pasted here would be committed, synced and shared with anyone the
    # config is sent to. Refuse loudly rather than quietly honouring it: a
    # rejected config costs a minute, a leaked key costs the account.
    for banned in ("api_key", "key", "token"):
        if banned in raw:
            raise ValueError(
                f"anthropic.{banned} must not be set in config.yaml — the API key "
                f"belongs in the environment (anthropic.api_key_env, default "
                f"{d.api_key_env}) or in a file named by anthropic.api_key_file")
    thinking = str(raw.get("thinking", d.thinking)).lower()
    if thinking not in ("disabled", "adaptive"):
        raise ValueError(
            f"anthropic.thinking must be 'disabled' or 'adaptive', got {thinking!r}")
    return AnthropicConfig(
        api_key_env=raw.get("api_key_env") or d.api_key_env,
        api_key_file=raw.get("api_key_file") or d.api_key_file,
        max_tokens=int(raw.get("max_tokens", d.max_tokens)),
        timeout_s=float(raw.get("timeout_s", d.timeout_s)),
        max_retries=int(raw.get("max_retries", d.max_retries)),
        retry_base_delay_s=float(raw.get("retry_base_delay_s", d.retry_base_delay_s)),
        retry_max_delay_s=float(raw.get("retry_max_delay_s", d.retry_max_delay_s)),
        max_concurrency=int(raw.get("max_concurrency", d.max_concurrency)),
        thinking=thinking,
    )


def _build_indexer(raw: dict[str, Any], top_raw: dict[str, Any]) -> IndexerConfig:
    """`indexer:` section, plus the backend-default heuristic that keeps every
    pre-2026-08-18 config.yaml behaving exactly as it did.

    Every one of those configs already has an `anthropic:` block (it was the
    only backend), and none of them has an `indexer:` block at all. A config
    that says nothing about `backend` but DOES name `anthropic:` is read as
    "this site already chose Anthropic" and keeps running unchanged — the
    alternative is a fleet of unattended indexer machines silently switching
    to a backend that needs a GPU and 3+ GB of first-run downloads. A brand
    new config (no `anthropic:` section either) defaults to `local`, per
    CLAUDE.md's task and `broll/docs/local-indexing-options-2026-08-17.md` §3.
    An explicit `indexer.backend` always wins over this heuristic.
    """
    d = IndexerConfig()
    backend = raw.get("backend")
    if backend is None:
        backend = "anthropic" if "anthropic" in top_raw else d.backend
    backend = str(backend).strip().lower()
    if backend not in ("local", "anthropic"):
        raise ValueError(
            f"indexer.backend must be 'local' or 'anthropic', got {backend!r}")

    model_tier_explicit = "model_tier" in raw
    model_tier = str(raw.get("model_tier", d.model_tier)).strip().lower()
    if model_tier not in ("good", "best"):
        raise ValueError(
            f"indexer.model_tier must be 'good' or 'best', got {model_tier!r}")

    return IndexerConfig(
        backend=backend,
        model_tier=model_tier,
        model_tier_explicit=model_tier_explicit,
        local_cache_dir=_env("BROLL_LOCAL_CACHE_DIR") or raw.get("local_cache_dir") or d.local_cache_dir,
        llama_server_path=_env("BROLL_LLAMA_SERVER_PATH") or raw.get("llama_server_path") or d.llama_server_path,
        dashboard_url=_env("BROLL_DASHBOARD_URL") or raw.get("dashboard_url") or d.dashboard_url,
        frames_per_call=int(raw.get("frames_per_call", d.frames_per_call)),
        gpu_layers=int(raw.get("gpu_layers", d.gpu_layers)),
        merge_similar_segments=bool(raw.get("merge_similar_segments", d.merge_similar_segments)),
    )


def load_config(path: str | Path) -> Config:
    path = Path(path)
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}

    db_raw = raw.get("db") or {}
    db = DbConfig(
        mode=db_raw.get("mode", "sqlite"),
        path=_env("BROLL_DB_PATH") or db_raw.get("path"),
        url=_env("BROLL_DB_URL") or db_raw.get("url"),
        token=_env("BROLL_DB_TOKEN") or db_raw.get("token"),
    )
    # Required, not defaulted (2026-08-17, COMMERCIAL_READINESS.md item 14). A
    # missing sqlite path used to reach the storage backend as None; a missing
    # api url reached requests as None. Both are the same operator mistake and
    # both deserve the key's name rather than a TypeError three frames down.
    if db.mode == "sqlite" and not db.path:
        raise ConfigError(
            f"{path}: db.path is required when db.mode is 'sqlite' "
            "(or set BROLL_DB_PATH). It is where the index is written."
        )
    if db.mode == "api" and not db.url:
        raise ConfigError(
            f"{path}: db.url is required when db.mode is 'api' (or set BROLL_DB_URL)."
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
        # Environment first for the three paths, because the GPU image sets them
        # and must not have to rewrite a config.yaml mounted read-only.
        python=_env("CCSYNC_WHISPER_PYTHON") or whisper_raw.get("python") or "",
        script=_env("CCSYNC_WHISPER_SCRIPT") or whisper_raw.get("script") or "",
        model=whisper_raw.get("model", whisper_defaults.model),
        model_dir=_env("CCSYNC_WHISPER_MODEL_DIR") or whisper_raw.get("model_dir") or "",
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
        cache_dir=(_env("BROLL_MODEL_CACHE", "FASTEMBED_CACHE_PATH")
                   or embedding_raw.get("cache_dir") or ""),
    )

    data_root = _env("BROLL_DATA_ROOT") or raw.get("data_root")
    if not data_root:
        raise ConfigError(
            f"{path}: data_root is required (or set BROLL_DATA_ROOT). It is where "
            "frames, proxies, posters, sprites and transcripts are written — tens "
            "of GB, so it is never guessed."
        )

    return Config(
        shares=_build_shares(raw.get("shares") or {}),
        data_root=Path(data_root),
        db=db,
        model=raw.get("model", "sonnet"),
        taxonomy_model=raw.get("taxonomy_model", "sonnet"),
        anthropic=_build_anthropic(raw.get("anthropic") or {}),
        sampling=sampling,
        whisper=whisper,
        embedding=embedding,
        indexer=_build_indexer(raw.get("indexer") or {}, raw),
    )
