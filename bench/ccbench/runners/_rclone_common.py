"""Shared plumbing for the two rclone-based runners (sftp, smb).

Both runners build an rclone "on the fly" remote spec string (no rclone.conf
needed -- see https://rclone.org/docs/#connection-strings) and then share the
same param-matrix expansion, transfer execution, verification and cleanup
logic. Only remote-spec construction and a couple of backend-specific flags
(e.g. --sftp-chunk-size only makes sense for sftp) differ between the two.

Direction handling:
- "up": purge the remote bench subfolder (untimed, and refused unless it is a
  `_bench` scratch path -- see ccbench.guard), then time
  `rclone copy dataset_dir -> remote`.
- "down": seed the remote bench subfolder with the dataset (untimed; **fails
  the run loudly** if the seed copy errors or times out), **empty the local
  destination** (a warm destination makes rclone skip everything and the run
  measures nothing), then time `rclone copy remote -> dest_dir`.

Cleanup ordering: a run never purges the remote *after* its own timed
transfer. Deleting several GB on the NAS immediately before the next timed run
warms the server's ARC/page cache and inflates the next number. Cleanup of the
remote scratch subtree happens once, after the whole matrix, via
`cleanup_endpoint()` on each runner (matrix.py drives it).

Measured bytes: `num_bytes` comes from rclone's own stats (`--use-json-log`,
`stats.bytes`), i.e. what it actually moved -- not from the dataset manifest,
which is identical whether rclone moved 40 GB or nothing at all. If the stats
can't be parsed the manifest total is used and `bytes_source` says
`manifest-fallback` so the row can be discounted.

--multi-thread-streams: only sweep it on "up" for backends that can actually
do multi-thread *uploads* (smb, local). SFTP cannot, so for sftp "up" the
sweep collapses to a single explicit 0 -- documented here and visible in the
params, never silently zeroed for a backend that would have benefited.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any

from ccbench import guard
from ccbench.result import RunResult, make_skipped

from . import base

# --sftp-chunk-size is in KiB here. The SFTP protocol's maximum total packet
# is 256 KiB, so 255Ki is the largest useful value (and rclone's own
# recommendation); anything expressed in megabytes is a protocol error waiting
# to happen. The old `sftp_chunk_size_mb` key is rejected outright below.
CHUNK_KEY = "sftp_chunk_size_kib"
LEGACY_CHUNK_KEY = "sftp_chunk_size_mb"
MAX_SFTP_CHUNK_KIB = 255
DEFAULT_CHUNK_SIZES_KIB = [MAX_SFTP_CHUNK_KIB]

# Machine-readable stats so we can read the bytes rclone actually moved.
STATS_FLAGS = ["--use-json-log", "--stats", "10s", "--stats-log-level", "NOTICE", "-v"]

_TRANSFERRED_RE = re.compile(
    r"Transferred:\s*([\d.]+)\s*([KMGTP]?i?B|Bytes?)\s*/", re.IGNORECASE
)


class SeedFailed(RuntimeError):
    """The untimed 'down' seed copy failed -- the timed run must not proceed."""


def available() -> tuple[bool, str]:
    return base.which("rclone")


def chunk_size_arg(kib: Any) -> str:
    """rclone --sftp-chunk-size argument for a KiB value, e.g. 255 -> '255Ki'."""
    return f"{int(kib)}Ki"


def build_param_matrix(
    cfg: dict[str, Any],
    direction: str,
    include_chunk_size: bool,
    multithread_up: bool = False,
) -> list[dict[str, Any]]:
    if LEGACY_CHUNK_KEY in cfg:
        raise ValueError(
            f"[params.rclone] {LEGACY_CHUNK_KEY} is no longer supported: the unit was megabytes, "
            f"but SFTP's maximum packet is 256 KiB. Rename it to {CHUNK_KEY} and give KiB values "
            f"(e.g. {CHUNK_KEY} = [32, 128, 255])."
        )

    transfers = base.expand_sweep(cfg.get("transfers"), [4])
    mts_raw = base.expand_sweep(cfg.get("multi_thread_streams"), [0])
    chunk_sizes = (
        base.expand_sweep(cfg.get(CHUNK_KEY), list(DEFAULT_CHUNK_SIZES_KIB))
        if include_chunk_size
        else [None]
    )

    combos: list[dict[str, Any]] = []
    seen: set[tuple] = set()
    # "down" always sweeps (rclone writes the local destination file).
    # "up" sweeps only for backends that support multi-thread uploads; for the
    # others it is a documented no-op, pinned to 0.
    sweep_mts = direction == "down" or multithread_up
    mts_options = mts_raw if sweep_mts else [0]
    for t in transfers:
        for mts in mts_options:
            for cs in chunk_sizes:
                params: dict[str, Any] = {"transfers": t, "multi_thread_streams": mts}
                if cs is not None:
                    params[CHUNK_KEY] = cs
                key = tuple(sorted(params.items()))
                if key in seen:
                    continue
                seen.add(key)
                combos.append(params)
    return combos


def _flags(params: dict[str, Any]) -> list[str]:
    flags = ["--transfers", str(params.get("transfers", 4))]
    mts = params.get("multi_thread_streams", 0)
    flags += ["--multi-thread-streams", str(mts)]
    if CHUNK_KEY in params:
        flags += ["--sftp-chunk-size", chunk_size_arg(params[CHUNK_KEY])]
    return flags


def parse_transferred_bytes(stderr: str) -> int | None:
    """Bytes rclone reports it actually transferred, or None if unparseable.

    Prefers the JSON log's cumulative `stats.bytes` (last stats record wins);
    falls back to the human 'Transferred: 1.234 GiB / ...' summary line.
    """
    latest: int | None = None
    for line in stderr.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            record = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        stats = record.get("stats")
        if isinstance(stats, dict) and isinstance(stats.get("bytes"), (int, float)):
            latest = int(stats["bytes"])
    if latest is not None:
        return latest

    matches = _TRANSFERRED_RE.findall(stderr)
    if matches:
        value, unit = matches[-1]
        return base.parse_size(value, unit)
    return None


def seed_remote(dataset_dir: Path, remote_root: str, timeout: float | None) -> None:
    """Untimed: make sure remote_root has the dataset already.

    `rclone copy` only transfers what's missing/changed, so this is cheap once
    seeded. Raises SeedFailed on a non-zero exit or a timeout -- a swallowed
    seed failure would produce a "download" of an empty remote and a
    meaningless (huge) throughput number.
    """
    try:
        rc, _out, err, _seconds = base.run_subprocess(
            ["rclone", "copy", str(dataset_dir), remote_root, "--transfers", "8"],
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise SeedFailed(f"seed copy timed out after {exc.timeout}s") from exc
    except OSError as exc:
        raise SeedFailed(f"seed copy could not start: {exc}") from exc
    if rc != 0:
        raise SeedFailed(f"seed copy exit {rc}: {guard.redact(base.tail(err, 500))}")


def cleanup_remote(remote_root: str, timeout: float = 120) -> None:
    """`rclone purge` the remote scratch subtree -- guarded by ccbench.guard.

    Raises DestructiveEndpointRefused when the target isn't a `_bench` path.

    A non-zero exit is tolerated: on the first run of a combo the path simply
    doesn't exist yet, and `purge` says so. A *timeout* or a failure to start
    rclone is not tolerated -- when this runs as the untimed pre-clean before
    an upload, "the purge may or may not have happened" means the next timed
    run may be copying into a warm destination, so it raises `CleanupFailed`
    and the caller fails the run instead of publishing the number.
    """
    guard.assert_scratch_path(remote_root, action="rclone purge")
    try:
        subprocess.run(
            ["rclone", "purge", remote_root], capture_output=True, text=True, timeout=timeout
        )
    except subprocess.TimeoutExpired as exc:
        raise guard.CleanupFailed(
            f"rclone purge of {guard.redact(remote_root)!r} timed out after {exc.timeout}s -- "
            f"the destination may still hold data from a previous run"
        ) from exc
    except OSError as exc:
        raise guard.CleanupFailed(
            f"rclone purge of {guard.redact(remote_root)!r} could not start: {exc}"
        ) from exc


def remote_listing(remote_root: str, timeout: float = 300) -> dict[str, int] | None:
    """{relative path: size} from `rclone lsjson -R --files-only`, or None if
    the listing failed. A listing is not a re-download -- it is the cheapest
    independent read-back available for an upload."""
    try:
        proc = subprocess.run(
            ["rclone", "lsjson", "-R", "--files-only", remote_root],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None
    if proc.returncode != 0 or not proc.stdout.strip():
        return None
    try:
        entries = json.loads(proc.stdout)
        return {str(e["Path"]).replace("\\", "/"): int(e["Size"]) for e in entries}
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        return None


def verify_upload(remote_root: str, manifest: list[dict[str, Any]]) -> tuple[bool | None, str]:
    """Check every manifest file exists at the remote with the right size.

    Returns (None, detail) when the listing itself was unavailable -- the
    caller must then record "exit-code-only", never a bare verified=True.
    Extra files at the remote (e.g. the dataset's own manifest.json) are
    ignored; missing or short files are not.
    """
    listing = remote_listing(remote_root)
    if listing is None:
        return None, "remote listing unavailable"
    missing = []
    wrong_size = []
    for record in manifest:
        rel = str(record["path"]).replace("\\", "/")
        if rel not in listing:
            missing.append(rel)
        elif listing[rel] != record["size"]:
            wrong_size.append(rel)
    if missing or wrong_size:
        return False, (
            f"remote listing mismatch: {len(missing)} missing, {len(wrong_size)} wrong size "
            f"(of {len(manifest)} manifest file(s))"
        )
    return True, f"listed {len(manifest)} file(s) at the remote with matching sizes"


def _failure(
    *,
    engine: str,
    dataset_name: str,
    direction: str,
    params: dict[str, Any],
    reason: str,
    lane: str,
    endpoint_label: str,
    repeat_index: int,
    loopback: bool,
) -> RunResult:
    return RunResult(
        engine=engine, dataset=dataset_name, direction=direction, params=params,
        seconds=0.0, num_bytes=0, MB_s=0.0, verified=False, ok=False,
        reason=reason, lane=lane, endpoint=endpoint_label, repeat_index=repeat_index,
        bytes_source="none", verify_method="none", loopback=loopback,
    )


def do_transfer(
    *,
    engine: str,
    dataset_name: str,
    dataset_dir: Path,
    direction: str,
    params: dict[str, Any],
    remote_root: str,
    verify: bool,
    keep_remote_data: bool,  # honoured by matrix.py's end-of-matrix cleanup, not here:
                             # a per-run cleanup would warm the cache for the next timed run
    dest_dir: Path | None,
    lane: str,
    endpoint_label: str,
    repeat_index: int,
    loopback: bool = False,
    seed_timeout: float | None = 1800,
    transfer_timeout: float | None = 3600,
) -> RunResult:
    ok, reason = available()
    if not ok:
        return make_skipped(
            engine, dataset_name, direction, params, reason, lane, endpoint_label,
            repeat_index, loopback,
        )

    flags = _flags(params)
    verify_root: Path | None = None

    fail = lambda why: _failure(  # noqa: E731 -- local shorthand, one shape of result
        engine=engine, dataset_name=dataset_name, direction=direction, params=params,
        reason=why, lane=lane, endpoint_label=endpoint_label, repeat_index=repeat_index,
        loopback=loopback,
    )

    try:
        if direction == "up":
            # Untimed pre-clean so a repeat can't be "fast" because the data
            # was already there. Deliberately BEFORE the timed run: cleaning
            # up after a run would warm the NAS cache for the next one.
            cleanup_remote(remote_root, timeout=120)
            rc, _out, err, seconds = base.run_subprocess(
                ["rclone", "copy", str(dataset_dir), remote_root, *flags, *STATS_FLAGS],
                timeout=transfer_timeout,
            )
        elif direction == "down":
            if dest_dir is None:
                raise ValueError("dest_dir required for 'down' direction")
            seed_remote(dataset_dir, remote_root, seed_timeout)
            guard.empty_dir(dest_dir, action="empty download destination")
            rc, _out, err, seconds = base.run_subprocess(
                ["rclone", "copy", remote_root, str(dest_dir), *flags, *STATS_FLAGS],
                timeout=transfer_timeout,
            )
            verify_root = dest_dir
        else:
            return make_skipped(
                engine, dataset_name, direction, params,
                f"unsupported direction for rclone runner: {direction}",
                lane, endpoint_label, repeat_index, loopback,
            )
    except guard.DestructiveEndpointRefused as exc:
        return fail(f"refused: {exc}")
    except guard.CleanupFailed as exc:
        return fail(f"pre-clean failed: {exc}")
    except SeedFailed as exc:
        return fail(f"seed failed: {exc}")
    except subprocess.TimeoutExpired as exc:
        return fail(f"timeout after {exc.timeout}s")
    except OSError as exc:
        return fail(f"could not start rclone: {exc}")

    if rc != 0:
        result = fail(f"rclone exit {rc}")
        # rclone echoes the whole connection string back in its "failed to
        # create file system for ..." errors, and that string carries
        # `pass=<obscured>` -- which `rclone reveal` turns back into the
        # plaintext. Never let it into results.jsonl.
        result.stderr_tail = guard.redact(base.tail(err))
        result.seconds = seconds
        return result

    moved = parse_transferred_bytes(err)
    if moved is None:
        num_bytes = base.manifest_bytes(dataset_dir)
        bytes_source = "manifest-fallback"
    else:
        num_bytes = moved
        bytes_source = "rclone-stats"

    expected_bytes = base.manifest_bytes(dataset_dir)
    if bytes_source == "rclone-stats":
        # Nothing (or not enough) actually moved: the destination was already
        # populated, in whole or in part. Timing this measures nothing, so say
        # so -- a partial row is worse than a missing one, because it looks
        # fast AND passes the presence+size verification of what did land.
        short = base.short_transfer_reason("rclone", num_bytes, expected_bytes)
        if short:
            result = fail(short)
            result.seconds = seconds
            result.stderr_tail = guard.redact(base.tail(err))
            return result

    verified = False
    verify_method = "none"
    extra_reason = ""
    if verify:
        if verify_root is not None:
            manifest = base.manifest_files(dataset_dir)
            verified, detail = base.spot_check(manifest, verify_root)
            verify_method = "spot-check-sha256"
            if not verified:
                extra_reason = f"verification failed: {detail}"
        else:
            # "up": read the remote back independently instead of trusting the
            # exit code. A listing is not a re-download.
            outcome, detail = verify_upload(remote_root, base.manifest_files(dataset_dir))
            if outcome is None:
                verify_method = "exit-code-only"
                extra_reason = f"{detail} -- exit code only, NOT verified"
            else:
                verify_method = "remote-size-listing"
                verified = outcome
                if not verified:
                    extra_reason = detail

    return RunResult(
        engine=engine,
        dataset=dataset_name,
        direction=direction,
        params=params,
        seconds=seconds,
        num_bytes=num_bytes,
        MB_s=base.mb_per_s(num_bytes, seconds),
        verified=verified,
        ok=True,
        reason=extra_reason,
        lane=lane,
        endpoint=endpoint_label,
        repeat_index=repeat_index,
        stderr_tail="",
        bytes_source=bytes_source,
        verify_method=verify_method,
        loopback=loopback,
    )
