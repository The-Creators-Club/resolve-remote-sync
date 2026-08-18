"""What differs between indexing b-roll and indexing music, in one object.

docs/MUSIC_INGEST_PLAN.md §2, 2026-08-18. The orchestrator, the loopback route
group, the gate, the checkpoints, the lease, the state file, the progress
window and the upload pump are the SAME for both kinds -- the plan's whole
premise is that music reuses them. What is not the same is a short list of
facts: which prefix the fleet routes hang off, which extensions may be dropped,
what the window says, whether the kind holds up proxy generation, and which
config keys an operator can tune.

Those facts live here rather than as `if self.kind == "music"` branches inside
`broll_ingest.py`, for one reason: the b-roll path must stay EXACTLY what it
was. A strategy object with b-roll's own values as the defaults means the
b-roll pipeline reads its own numbers through one extra attribute lookup and
nothing else -- `tests/test_broll_ingest.py` runs unchanged, and
`tests/test_music_ingest.py` asserts that the b-roll kind still resolves to the
same code path rather than to a copy of it.

**A kind is data, not behaviour.** The per-track pipeline (proxy/sprite/frames/
describe against probe/transcode/peaks/embed) is the one thing that genuinely
differs, and it is a subclass override in `music_ingest.py`, where it can be
read next to the b-roll version it mirrors. Anything expressible as a value
belongs here; anything that needs the orchestrator's state does not.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

# The two names a kind may have. They appear in the state filename, the fleet
# route prefix, the loopback route prefix and the reporter section, so they are
# a wire contract in four places at once.
BROLL = "broll"
MUSIC = "music"


class IngestKind:
    """One kind of ingest, as everything shared needs to see it.

    Frozen by convention (nothing mutates an instance; the two module-level
    singletons are shared by every orchestrator, every loopback request thread
    and the tray). Values only -- see the module docstring.
    """

    def __init__(
        self,
        name: str,
        *,
        label: str,
        api_prefix: str,
        loopback_prefix: str,
        state_filename: str,
        config_prefix: str,
        window_title: str,
        unit: str,
        media_word: str,
        exts,
        blocks_proxies: bool,
        uses_tier: bool,
        report_section: str,
        max_prepare_items: int,
        blocking_reason: str = "",
        finished_states=None,
    ) -> None:
        self.name = name
        # How an editor refers to it in a sentence: "indexing b-roll",
        # "ccsync-companion: music". Never capitalised here -- the callers that
        # need a capital have a title to put it in.
        self.label = label
        self.api_prefix = api_prefix
        self.loopback_prefix = loopback_prefix
        self.state_filename = state_filename
        self.config_prefix = config_prefix
        self.window_title = window_title
        # "clip" / "track": the noun the progress window counts in. b-roll's
        # window said "clips" before this existed and still does.
        self.unit = unit
        # What a file that is not of this kind is not: "a video this machine
        # can index" / "an audio file this machine can index".
        self.media_word = media_word
        # A frozenset, or a zero-argument callable returning one. b-roll's
        # list lives in `broll_server` (the picker's folder walk and the
        # prepare refusal read it there) and that module imports THIS one, so
        # it arrives as a callable rather than as a fourth copy of the list.
        self._exts = exts
        # Whether a running batch of this kind stands proxy generation down.
        # TRUE for b-roll (both want the same GPU, and the owner reversed the
        # priority on 2026-08-18 so indexing wins); FALSE for music, which
        # never touches the GPU -- ~90 ms per 10 s window on a CPU core.
        self.blocks_proxies = blocks_proxies
        # Whether the batch's settings carry a model tier. Music has none: the
        # CLAP audio tower is one 280 MB artefact and there is nothing to
        # choose between (plan §1, "the tier concept does not apply").
        self.uses_tier = uses_tier
        self.report_section = report_section
        self.max_prepare_items = max_prepare_items
        self._blocking_reason = blocking_reason
        # Item states meaning "nothing left to do with this one", or None for
        # b-roll's own four (`broll_ingest.ITEM_FINISHED`). Music adds
        # `queued_for_base_rig`: the item is finished as far as THIS machine's
        # ledger is concerned and the work continues on the base rig, so an
        # orchestrator that kept picking it up would never end the batch.
        self.finished_states = (frozenset(finished_states)
                                if finished_states else None)

    @property
    def exts(self) -> frozenset:
        return frozenset(self._exts() if callable(self._exts) else self._exts)

    # -- config keys -------------------------------------------------------
    def cfg_key(self, suffix: str) -> str:
        """`broll_ingest_idle_seconds` / `music_ingest_idle_seconds`.

        One helper rather than eleven constants, because every one of these
        keys is `<prefix>_<suffix>` and an operator who has learned one has
        learned both.
        """
        return f"{self.config_prefix}_{suffix}"

    # -- the loopback ------------------------------------------------------
    def upload_url(self, staging_id: str, local_id: str) -> str:
        """The PUT path this kind's `prepare` hands back per item."""
        return f"{self.loopback_prefix}/upload/{staging_id}/{local_id}"

    def is_accepted_ext(self, name: str) -> bool:
        import os

        return os.path.splitext(str(name or ""))[1].lower() in self.exts

    # -- staging -----------------------------------------------------------
    def staging_root(self, cfg: Optional[dict[str, Any]]) -> Optional[Path]:
        """Where this kind stages dropped files on this machine, or None.

        Imported lazily on purpose: `broll_server` dispatches the loopback
        routes for BOTH kinds and therefore imports this module, so a
        module-level import back into it would be a cycle.
        """
        from . import broll_server

        cfg = cfg or {}
        override = str(cfg.get(self.cfg_key("staging_dir")) or "").strip()
        if override:
            return Path(override)
        if self.name == MUSIC:
            from . import music_server

            mount = music_server.default_music_mount(cfg)
            if not mount:
                return None
            return Path(mount) / broll_server.INGEST_DIR_NAME
        return broll_server.ingest_staging_root(cfg)

    def blocking_sentence(self) -> Optional[str]:
        """What the PROXY generator shows while it stands aside, or None."""
        return self._blocking_reason or None

    def __repr__(self) -> str:  # pragma: no cover - diagnostics only
        return f"<IngestKind {self.name}>"


def _broll_exts() -> frozenset[str]:
    """b-roll's list, read from where it has always lived rather than copied:
    `broll_server.INGEST_VIDEO_EXTS` is what the picker's folder walk, the
    prepare refusal and the page all agree on, and a fourth copy here would be
    the one that drifts."""
    from . import broll_server

    return frozenset(broll_server.INGEST_VIDEO_EXTS)


# What may be dropped on the music page. `musicweb.ingest_batches.AUDIO_EXTS`
# and `musicweb.routes_ingest.AUDIO_EXTS`, which are themselves copies of
# `music_index.config`'s -- the container cannot import the indexer and this
# companion can import neither. Three places that must agree or a folder drop
# offers files the server then refuses with a 422 naming them.
MUSIC_EXTS = frozenset({
    ".wav", ".mp3", ".flac", ".aac", ".m4a", ".ogg", ".aiff", ".aif", ".opus",
})

# What .ogg becomes on the way in, applied on THIS side so that the bytes
# crossing the wire are the bytes that land (`musicweb.ingest_batches.
# TRANSCODE_EXTS`).
MUSIC_TRANSCODE_EXTS = frozenset({".ogg"})


BROLL_KIND = IngestKind(
    BROLL,
    label="b-roll",
    api_prefix="/broll/api/fleet/ingest",
    loopback_prefix="/broll/ingest",
    state_filename="broll_ingest.json",
    config_prefix="broll_ingest",
    window_title="INDEXING B-ROLL",
    unit="clip",
    media_word="a video this machine can index",
    exts=_broll_exts,
    blocks_proxies=True,
    uses_tier=True,
    report_section="broll_ingest",
    max_prepare_items=2000,
    blocking_reason="indexing b-roll first",
)

MUSIC_KIND = IngestKind(
    MUSIC,
    label="music",
    api_prefix="/music/api/fleet/ingest",
    loopback_prefix="/music/ingest",
    state_filename="music_ingest.json",
    config_prefix="music_ingest",
    window_title="INDEXING MUSIC",
    unit="track",
    media_word="an audio file this machine can index",
    exts=MUSIC_EXTS,
    # Music never blocks proxy generation (plan §2): it needs no GPU, and an
    # editor who dropped an album should not find their proxies stopped for it.
    blocks_proxies=False,
    uses_tier=False,
    report_section="music_ingest",
    # `musicweb.config.MAX_BATCH_ITEMS`. Two orders of magnitude below
    # b-roll's, because a music drop is an album and a b-roll drop is a camera
    # card -- and the server refuses a 501st item, so offering to stage 2,000
    # would be an offer this machine cannot keep.
    max_prepare_items=500,
    # `musicweb.ingest_batches.ITEM_TERMINAL`, and the fifth member is the
    # whole fallback: a companion that cannot embed uploads the file and
    # leaves a base-rig queue row, which ends the item HERE.
    finished_states=("live", "duplicate", "cancelled", "skipped",
                     "queued_for_base_rig"),
)

KINDS = {BROLL: BROLL_KIND, MUSIC: MUSIC_KIND}


def kind_for(name: str) -> IngestKind:
    """A kind by name, defaulting to b-roll.

    Defaulting rather than raising: this is reached from route dispatch and
    from a resumed state file, and neither is a place to take the tray down
    over a string.
    """
    return KINDS.get(str(name or "").strip().lower(), BROLL_KIND)
