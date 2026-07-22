"""Deterministic synthetic dataset generator for the benchmark harness.

Two profiles:
- "large": a handful of big (GiB-scale) incompressible files with video-ish
  extensions (.braw/.mov) -- stand-ins for camera originals / proxies (lanes A/B).
- "small": hundreds of small-to-medium files, log-uniform sized, nested three
  directories deep, mixed asset extensions -- stand-in for lane C (everything
  else: audio, GFX, AE, subs, stills).

Data is generated with a seeded PRNG (random.Random) rather than plain zeros
or a repeating pattern so that gzip/sparse-file tricks in a transport can't
fake a good result -- the compressed size must stay ~= the original size.
random.Random(seed).randbytes(n) is deterministic (same seed -> same bytes)
and its output is high-entropy pseudorandom, which is sufficient to defeat
gzip: it is not being used for any cryptographic purpose here, just to
produce reproducible incompressible bytes without extra dependencies
(no pycryptodome/os.urandom-with-fixed-seed available in the stdlib).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

LARGE_EXTENSIONS = [".braw", ".mov"]
SMALL_EXTENSIONS = [".wav", ".png", ".aep", ".srt", ".psd"]

# Fixed name pools so nesting is deterministic and reads like a real project tree.
SMALL_LEVEL1 = ["Audio", "GFX", "Docs", "Stills"]
SMALL_LEVEL2 = ["Music", "SFX", "Titles", "Graphics", "Client", "Archive"]
SMALL_LEVEL3 = ["v1", "v2", "final", "draft", "misc"]

DEFAULT_CHUNK = 64 * 1024 * 1024  # 64 MiB streaming write/hash chunk

MANIFEST_NAME = "manifest.json"


@dataclass
class FileRecord:
    path: str  # relative to dataset out_dir, forward-slash separated
    size: int
    sha256: str
    profile: str

    def to_dict(self) -> dict[str, Any]:
        return {"path": self.path, "size": self.size, "sha256": self.sha256, "profile": self.profile}


def _write_random_file(path: Path, size: int, rng: random.Random, chunk_size: int = DEFAULT_CHUNK) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    h = hashlib.sha256()
    remaining = size
    with open(path, "wb") as f:
        while remaining > 0:
            n = min(chunk_size, remaining)
            chunk = rng.randbytes(n)
            f.write(chunk)
            h.update(chunk)
            remaining -= n
    return h.hexdigest()


def _log_uniform_size(rng: random.Random, min_bytes: int, max_bytes: int) -> int:
    lo, hi = math.log(min_bytes), math.log(max_bytes)
    return int(math.exp(rng.uniform(lo, hi)))


def generate_large(
    out_dir: Path,
    seed: int,
    count: int = 3,
    size_bytes: int = 4 * 1024**3,
) -> list[FileRecord]:
    rng = random.Random(f"{seed}:large")
    root = out_dir / "large"
    records: list[FileRecord] = []
    for i in range(count):
        ext = LARGE_EXTENSIONS[i % len(LARGE_EXTENSIONS)]
        name = f"clip_{i:04d}{ext}"
        path = root / name
        digest = _write_random_file(path, size_bytes, rng)
        records.append(
            FileRecord(
                path="/".join(("large", name)),
                size=size_bytes,
                sha256=digest,
                profile="large",
            )
        )
    return records


def generate_small(
    out_dir: Path,
    seed: int,
    count: int = 400,
    min_bytes: int = 50 * 1024,
    max_bytes: int = 20 * 1024 * 1024,
) -> list[FileRecord]:
    rng = random.Random(f"{seed}:small")
    root = out_dir / "small"
    records: list[FileRecord] = []
    for i in range(count):
        l1 = SMALL_LEVEL1[rng.randrange(len(SMALL_LEVEL1))]
        l2 = SMALL_LEVEL2[rng.randrange(len(SMALL_LEVEL2))]
        l3 = SMALL_LEVEL3[rng.randrange(len(SMALL_LEVEL3))]
        ext = SMALL_EXTENSIONS[rng.randrange(len(SMALL_EXTENSIONS))]
        name = f"asset_{i:04d}{ext}"
        rel = "/".join(("small", l1, l2, l3, name))
        path = out_dir / "small" / l1 / l2 / l3 / name
        size = _log_uniform_size(rng, min_bytes, max_bytes)
        digest = _write_random_file(path, size, rng)
        records.append(FileRecord(path=rel, size=size, sha256=digest, profile="small"))
    return records


def write_manifest(out_dir: Path, seed: int, profile: str, records: list[FileRecord]) -> Path:
    manifest = {
        "profile": profile,
        "seed": seed,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "root": str(out_dir),
        "file_count": len(records),
        "total_bytes": sum(r.size for r in records),
        "files": [r.to_dict() for r in records],
    }
    manifest_path = out_dir / MANIFEST_NAME
    out_dir.mkdir(parents=True, exist_ok=True)
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, sort_keys=True)
        f.write("\n")
    return manifest_path


def read_manifest(out_dir: Path) -> dict[str, Any]:
    with open(out_dir / MANIFEST_NAME, "r", encoding="utf-8") as f:
        return json.load(f)


def generate(
    out_dir: Path,
    profile: str,
    seed: int = 1337,
    large_count: int = 3,
    large_size_bytes: int = 4 * 1024**3,
    small_count: int = 400,
    small_min_bytes: int = 50 * 1024,
    small_max_bytes: int = 20 * 1024 * 1024,
) -> Path:
    """Generate the requested profile(s) under out_dir and write manifest.json.
    Returns the manifest path. Deterministic for a given seed + parameters."""
    out_dir = Path(out_dir)
    records: list[FileRecord] = []
    if profile in ("large", "both"):
        records.extend(generate_large(out_dir, seed, large_count, large_size_bytes))
    if profile in ("small", "both"):
        records.extend(generate_small(out_dir, seed, small_count, small_min_bytes, small_max_bytes))
    if profile not in ("large", "small", "both"):
        raise ValueError(f"unknown profile: {profile!r}")
    return write_manifest(out_dir, seed, profile, records)


def add_subparser(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser("dataset", help="generate a synthetic benchmark dataset")
    p.add_argument("--out", required=True, help="output directory for the dataset")
    p.add_argument("--profile", choices=["large", "small", "both"], default="both")
    p.add_argument("--seed", type=int, default=1337)
    p.add_argument("--large-count", type=int, default=3)
    p.add_argument("--large-size-gib", type=float, default=4.0)
    p.add_argument("--small-count", type=int, default=400)
    p.add_argument("--small-min-kib", type=float, default=50.0)
    p.add_argument("--small-max-mib", type=float, default=20.0)
    p.set_defaults(func=_cli_run)


def _cli_run(args: argparse.Namespace) -> int:
    manifest_path = generate(
        out_dir=Path(args.out),
        profile=args.profile,
        seed=args.seed,
        large_count=args.large_count,
        large_size_bytes=int(args.large_size_gib * 1024**3),
        small_count=args.small_count,
        small_min_bytes=int(args.small_min_kib * 1024),
        small_max_bytes=int(args.small_max_mib * 1024 * 1024),
    )
    manifest = read_manifest(Path(args.out))
    print(f"wrote {manifest['file_count']} files ({manifest['total_bytes'] / (1024**2):.1f} MiB) -> {manifest_path}")
    return 0
