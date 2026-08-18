# VENDORED VERBATIM from music/indexer/music_models.py -- DO NOT EDIT HERE.
# Edit the indexer's copy and re-copy it in BELOW THE MARKER LINE at the end of
# this header; everything under that line is byte-identical to the source on
# purpose, so the two trees can be compared mechanically -- and they are:
# tools/release.ps1 (and tools/release_macos.sh) strip this header, byte-compare
# the rest against the source and REFUSE to build on a mismatch, and
# server/tests/test_cross_component.py pins the same comparison in the suites.
# Same mechanism as ccsync_companion/broll_vlm/ (2026-08-18) and
# ccsync_companion/ytdl_common.py (2026-08-14).
#
# Why a copy and not an import (docs/MUSIC_INGEST_PLAN.md step 3): the
# companion is a frozen, windowed PyInstaller build and `music_index` reaches
# torch, librosa and transformers -- gigabytes -- for two modules that between
# them need nothing but the stdlib and numpy. The MODULE NAMES are unchanged so
# nothing inside them has to be rewritten.
#
# What drift here would cost is not a crash: a mel that differs in its last
# bits produces a plausible embedding of the wrong audio, in the wrong place in
# a 512-dimensional space that every cosine in the library is measured against.
# Nothing downstream can detect it.
#
# The marker is the LAST line of this header and appears exactly once (both the
# gate and the test refuse an absent or ambiguous marker rather than skipping).
# Nothing but the source file's own bytes may follow it.
# --- vendored content below, byte-identical ---
"""The music sidecar model catalogue: which artefact, which sha256, how big.

One place, so `export_audio_encoder.py` (which produces the artefact), the
companion's `music_clap_sidecar.py` (which downloads it) and the docs all read
the same facts instead of three copies drifting apart -- exactly the job
`broll_index/local_models.py` does for the local-VLM tiers.

Unlike the b-roll tiers, **this artefact is ours**: there is no Hugging Face
repo to point a sha256 at. `export_audio_encoder.py` exports the CLAP audio
tower to ONNX on the base rig, verifies it against the torch model, and the
resulting file is published to the vendor release feed
(`docs/RELEASE_FEED.md`) beside the companion binaries. So the sha256s below
are read off the artefact THIS repo produced, and the version string is the
only thing standing between a fleet and a silently different embedding space:

  **bump `version` whenever the weights, the graph or the feature parameters
  change** -- including a change of `hf_model`. An embedding produced by a
  different tower is a plausible-looking vector in the wrong space; nothing
  downstream (cosine thresholds, tags, search) can detect it, and every track
  ingested under the old artefact would have to be re-embedded. The version is
  in the FILENAME for the same reason: two artefacts can coexist on the feed
  and on an editor's disk during a migration.

Licence: the weights are LAION's CLAP checkpoint (Apache-2.0 model code,
CC0-1.0 weights as published on the model card); the export adds no third-party
code. `tools/check_licenses.py` does not read this file -- it reads
requirements locks -- so the string here is documentation for the notices
file, not a gate.
"""
from __future__ import annotations

# Where a fleet fetches the artefact from. `{base}` is the release feed's
# directory prefix -- the parent of `channel.json`, i.e. exactly the
# `DASH_RELEASE_FEED_URL` a site is configured with, minus the filename. No
# vendor host is hardcoded anywhere in this repo (CLAUDE.md: "no customer's
# name in code"; the same rule keeps OUR host out of it) and the companion
# resolves `{base}` from the dashboard's site payload, host-allow-listed the
# way `broll_vlm_sidecar` allow-lists github.com/huggingface.co.
#
# A SIBLING of channel.json, never a sub-directory (changed 2026-08-18, WP 3):
# the feed's host of record is GitHub Releases, whose assets live in ONE FLAT
# NAMESPACE per tag -- there are no directories and an asset name containing a
# slash is not uploadable (docs/RELEASE_FEED.md 3.1). A `models/` prefix would
# therefore have 404'd on the only host this feed is actually served from,
# while looking correct against a plain bucket. The version is in the filename
# for exactly this reason, so a flat namespace still holds two artefacts at
# once during a migration.
FEED_URL_TEMPLATE = "{base}/{filename}"

# Placeholder written by `export_audio_encoder.py --print-catalogue` when an
# artefact has not been produced yet. A sidecar MUST refuse to download an
# entry still carrying it: an unpinned model is an unverified download.
UNPINNED = "TODO-sha256"

MODELS: dict[str, dict] = {
    "clap-audio": {
        # ---- identity -----------------------------------------------------
        "version": "1",
        "hf_model": "laion/larger_clap_music_and_speech",
        "what": "CLAP audio tower (HTSAT) + audio_projection + L2 normalise",
        # ---- the two files ------------------------------------------------
        "onnx_name": "music-clap-audio-1.onnx",
        "params_name": "music-clap-audio-1.params.json",
        # Read off the artefact exported on the base rig 2026-08-18
        # (torch 2.6.0+cu124 / transformers 5.14.1, opset 17): cosine vs the
        # torch model 0.9999999 min over 80 windows of 20 library tracks and
        # over their 20 mean-pooled track vectors -- the run's own
        # `report.md`. Re-exporting changes the params sha (it carries
        # `exported_at`), so this block is updated per export, not per model.
        "sha256": {
            "music-clap-audio-1.onnx":
                "170bc152679ec871e5e53f5fe6a7d0ba5d6a8f1ec27f74d43ca5dc828fd2e27f",
            "music-clap-audio-1.params.json":
                "8d537b04e28d1701f0694391bff391b8ad632dbc1f76d4b4117edd33fad8bc6c",
        },
        "size_bytes": {
            "music-clap-audio-1.onnx": 279_978_254,
            "music-clap-audio-1.params.json": 1_355,
        },
        # ---- what the sidecar needs to know without opening the file ------
        "dim": 512,
        # fp32, deliberately, though the exporter also writes a
        # `music-clap-audio-1.fp16.onnx` (141.0 MB vs 280.0 MB, cosine 0.99997
        # vs the torch model instead of 0.9999999 -- measured, same run). Half
        # the download, but onnxruntime's CPU provider runs fp16 by inserting
        # casts, and CPU is what an editor laptop without a usable GPU EP
        # actually has. It is not pinned here until someone measures it being
        # faster on a machine in the field; the numbers are in report.md.
        "precision": "fp32",
        "params_version": 1,
        "license": "CC0/Apache-2.0 per laion/clap",
    },
}

DEFAULT_MODEL = "clap-audio"


def model(key: str = DEFAULT_MODEL) -> dict:
    entry = MODELS.get((key or DEFAULT_MODEL).strip().lower())
    if entry is None:
        raise ValueError(
            f"unknown music model {key!r} -- expected one of {', '.join(MODELS)}")
    return entry


def filenames(key: str = DEFAULT_MODEL) -> tuple[str, str]:
    """(onnx, params) -- the pair a sidecar must have BOTH of to embed."""
    entry = model(key)
    return entry["onnx_name"], entry["params_name"]


def is_pinned(key: str = DEFAULT_MODEL) -> bool:
    """False while any sha256 is still the placeholder. The download path is
    expected to refuse in that case rather than fetch an unverifiable file."""
    return all(v and v != UNPINNED for v in model(key)["sha256"].values())


def urls(base: str, key: str = DEFAULT_MODEL) -> dict[str, str]:
    """filename -> absolute URL under a feed base (no trailing slash needed)."""
    base = (base or "").rstrip("/")
    if not base:
        raise ValueError("no release-feed base URL: a fleet with no feed "
                         "configured cannot fetch the CLAP audio artefact")
    return {name: FEED_URL_TEMPLATE.format(base=base, filename=name)
            for name in filenames(key)}


def expected_sha256(filename: str, key: str = DEFAULT_MODEL) -> str:
    entry = model(key)
    try:
        return entry["sha256"][filename]
    except KeyError:
        raise ValueError(
            f"{filename!r} is not part of the {key!r} artefact "
            f"({', '.join(entry['sha256'])})") from None
