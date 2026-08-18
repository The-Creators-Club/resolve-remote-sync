"""What "the same runtime" means, in one function (ZERO_TOUCH_PLAN.md WP K).

The dashboard's CODE can be updated over the air: a signed `dashboard`
record in the vendor feed, downloaded and verified by the running dashboard,
staged into `/data/code/<version>/` and re-exec'd. Its RUNTIME cannot -- the
container image holds Python itself, the hash-pinned dependency closure and
the sidecars, and this process has no Docker socket and never will
(ZERO_TOUCH_PLAN.md section 5, "no Docker socket, no self-recreate").

So every bundle carries a `runtime_id` and every image is baked with one, and
a code update is offered ONLY when the two agree. That is the whole two-tier
rule:

    same runtime_id  -> code update    -> one button in the dashboard
    different        -> runtime update -> the NAS UI's own image update click

A code update that quietly brought a new dependency would import a module the
venv does not have, half way through a boot, on a customer's NAS, with the
previous tree already swapped away. Refusing is the only honest answer, and
this id is what makes the refusal automatic rather than a release-note.

DEFINITION (stable, and deliberately narrow):

    sha256(b"ccsync-runtime-id-v1\\n"
           + b"base_image=" + <the Dockerfile's base image reference> + b"\\n"
           + b"lock_sha256=" + sha256(<requirements.lock bytes>).hexdigest() + b"\\n")

Two inputs, because those are the two things that decide what
`import x` can find inside the container: the base image (Python's own
version and the OS libraries under it) and the hash-pinned lockfile the image
installs with `--require-hashes`. Nothing else belongs in it -- adding, say,
the Dockerfile's whole text would make every comment edit a "runtime change"
that forces every customer to click through their NAS UI.

ONE COPY, TWO CALLERS. `tools/build_dashboard_bundle.py` imports this to
stamp a bundle; `dashboard/deploy/Dockerfile` imports it at build time to
write `/venv/.runtime-id`, and `dashboard_update.py` /
`dashboard/deploy/select_code_root.py` read that file back. A second
implementation of this recipe would be a second answer to "may this update be
applied", which is exactly the question that must have one.

The base image is passed in by the Dockerfile (its own `ARG BASE_IMAGE`, so a
`--build-arg` override is reflected honestly) and parsed out of the
Dockerfile text by the builder. If those two ever disagree -- someone built
the image with `--build-arg BASE_IMAGE=...` -- the ids differ, every update
is refused as a runtime mismatch, and the operator is told why. Fail-safe,
not silent.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

RUNTIME_PREFIX = b"ccsync-runtime-id-v1\n"

# Where the image writes its own id (Dockerfile) and where everything else
# reads it back from. Inside /venv rather than /app because it describes the
# VENV: /app's code is what gets replaced over the air, /venv's contents are
# what cannot be.
IMAGE_RUNTIME_ID_PATH = "/venv/.runtime-id"

# `ARG BASE_IMAGE=python:3.12.7-slim@sha256:...` -- the ONE line in the
# Dockerfile that names the base. Anchored to ARG so a stray `FROM ${BASE_IMAGE}`
# or a comment quoting the digest cannot be mistaken for it.
_ARG_BASE_IMAGE = re.compile(r"^\s*ARG\s+BASE_IMAGE\s*=\s*(?P<value>\S+)\s*$", re.M)


def runtime_id(lock_bytes: bytes, base_image: str) -> str:
    """The 64-hex runtime id for a (lockfile, base image) pair.

    Bytes in, string out, no filesystem: the two callers reach their inputs
    very differently (a repo checkout vs. a half-built image layer) and only
    the recipe is shared."""
    lock_digest = hashlib.sha256(lock_bytes).hexdigest()
    message = (
        RUNTIME_PREFIX
        + b"base_image=" + str(base_image).strip().encode("utf-8") + b"\n"
        + b"lock_sha256=" + lock_digest.encode("ascii") + b"\n"
    )
    return hashlib.sha256(message).hexdigest()


def base_image_from_dockerfile(text: str) -> str:
    """The base image reference declared by `ARG BASE_IMAGE=`.

    Raises ValueError rather than guessing: a Dockerfile that stopped
    declaring one would otherwise silently produce a runtime_id that means
    nothing, and every customer's dashboard would then either refuse every
    update or accept one it should not have."""
    match = _ARG_BASE_IMAGE.search(text)
    if match is None:
        raise ValueError(
            "the Dockerfile declares no `ARG BASE_IMAGE=` line -- the runtime id "
            "cannot be computed without the base image it pins")
    return match.group("value").strip()


def runtime_id_from_paths(lock_path: str | Path, dockerfile_path: str | Path | None = None,
                          base_image: str = "") -> str:
    """Read the lockfile (and, unless `base_image` is given, the Dockerfile)
    and return the id. `base_image` wins so the image build can pass its own
    `ARG BASE_IMAGE` -- including one overridden with `--build-arg`."""
    lock_bytes = Path(lock_path).read_bytes()
    if not base_image:
        if dockerfile_path is None:
            raise ValueError("runtime_id_from_paths needs a dockerfile_path or a base_image")
        base_image = base_image_from_dockerfile(
            Path(dockerfile_path).read_text(encoding="utf-8"))
    return runtime_id(lock_bytes, base_image)


def read_image_runtime_id(path: str | Path = IMAGE_RUNTIME_ID_PATH) -> str:
    """The id baked into THIS image, or "" if there is none.

    An empty answer is a real, supported state, not an error: bind-mount mode
    has no image at all, and an image built before WP K landed has no marker.
    Both mean "no over-the-air code update here", which every caller must
    handle by refusing with a reason rather than by crashing."""
    try:
        return Path(path).read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError):
        return ""
