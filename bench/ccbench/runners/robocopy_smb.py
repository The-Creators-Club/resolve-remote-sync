"""Raw SMB copy via robocopy (Windows only) -- the "no extra tooling"
baseline every other engine has to beat. Sweeps /MT:{1,8,16,32} against a UNC
path (or, for selftest, a plain local directory -- robocopy doesn't care).

endpoint config (bench.toml [endpoints.smb], reused for this runner too):
    unc_path  -- e.g. \\\\host\\share\\Creators_Club\\_bench
    local_test_dir  -- selftest escape hatch, see rclone_sftp.py (marks the
                       run loopback=True: not comparable with network runs)

Every deletion here (pre-clean of the target, emptying the download
destination) goes through ccbench.guard, so a `unc_path` pointing at a live
project subtree is refused rather than wiped. Cleanup of the seeded target
happens once after the whole matrix (`cleanup_endpoint`), not after each timed
run -- deleting several GB on the NAS right before the next run warms its
cache and inflates the next number.

Bytes are read from robocopy's own job summary ("Bytes : ... copied ...") so
the reported throughput reflects what actually moved; if the summary can't be
parsed the dataset manifest total is used and `bytes_source` says so.

robocopy exit codes 0-7 are all "success" (bit flags for files
copied/skipped/mismatched); >=8 means at least one failure.
"""

from __future__ import annotations

import platform
import re
from pathlib import Path
from typing import Any

from ccbench import guard
from ccbench.result import RunResult, make_skipped

from . import base

ENGINE = "robocopy_smb"

ROBOCOPY_FAILURE_THRESHOLD = 8

# "   Bytes :   262.1 k   262.1 k         0         0         0         0"
# or "   Bytes :    268435456    268435456    0    0    0    0"
_BYTES_LINE_RE = re.compile(r"^\s*Bytes\s*:\s*(.+)$", re.MULTILINE)
_BYTES_TOKEN_RE = re.compile(r"(\d+(?:\.\d+)?)\s*([kmgt])?", re.IGNORECASE)


def available() -> tuple[bool, str]:
    if platform.system() != "Windows":
        return False, "robocopy is Windows-only"
    return base.which("robocopy")


def param_matrix(cfg: dict[str, Any], direction: str) -> list[dict[str, Any]]:
    mt_values = base.expand_sweep(cfg.get("mt"), [1, 8, 16, 32])
    return [{"mt": mt} for mt in mt_values]


def parse_copied_bytes(output: str) -> int | None:
    """Bytes robocopy says it copied (2nd column of its 'Bytes :' summary)."""
    match = _BYTES_LINE_RE.search(output)
    if not match:
        return None
    tokens = _BYTES_TOKEN_RE.findall(match.group(1))
    if len(tokens) < 2:
        return None
    value, suffix = tokens[1]  # Total, Copied, Skipped, Mismatch, FAILED, Extras
    return base.parse_size(value, suffix or "b")  # robocopy's k/m/g are binary


def _target_root(endpoint: dict[str, Any], dataset_name: str, direction: str) -> Path:
    base_path = endpoint.get("local_test_dir") or endpoint.get("unc_path")
    if not base_path:
        raise ValueError("robocopy_smb endpoint needs 'unc_path' (or 'local_test_dir' for selftest)")
    root = Path(base_path)
    if endpoint.get("local_test_dir"):
        root = root / "_bench_robocopy"
    return root / dataset_name / direction


def _robocopy(src: Path, dst: Path, mt: int, timeout: float | None) -> tuple[int, str, str, float]:
    dst.mkdir(parents=True, exist_ok=True)
    cmd = [
        "robocopy",
        str(src),
        str(dst),
        "/E",
        f"/MT:{mt}",
        "/R:1",
        "/W:1",
        "/NFL",
        "/NDL",
        "/NP",
        "/NJH",
    ]
    return base.run_subprocess(cmd, timeout=timeout)


def run(
    dataset_dir: Path,
    direction: str,
    endpoint: dict[str, Any],
    params: dict[str, Any],
    *,
    dataset_name: str = "",
    verify: bool = True,
    # honoured by matrix.py's end-of-matrix cleanup, not here: a per-run
    # cleanup would warm the NAS cache for the next timed run
    keep_remote_data: bool = False,
    dest_dir: Path | None = None,
    lane: str = "",
    repeat_index: int = 0,
    seed_timeout: float | None = 1800,
    transfer_timeout: float | None = 3600,
) -> RunResult:
    ok, reason = available()
    dataset_name = dataset_name or Path(dataset_dir).name
    loopback = bool(endpoint.get("local_test_dir"))
    if not ok:
        return make_skipped(
            ENGINE, dataset_name, direction, params, reason, lane, "", repeat_index, loopback
        )

    mt = int(params.get("mt", 8))
    dataset_dir = Path(dataset_dir)
    target_root = _target_root(endpoint, dataset_name, direction)
    label = str(endpoint.get("unc_path") or endpoint.get("local_test_dir") or "smb")

    def _failed(why: str) -> RunResult:
        return RunResult(
            engine=ENGINE, dataset=dataset_name, direction=direction, params=params,
            seconds=0.0, num_bytes=0, MB_s=0.0, verified=False, ok=False,
            reason=why, lane=lane, endpoint=label, repeat_index=repeat_index,
            bytes_source="none", verify_method="none", loopback=loopback,
        )

    verify_root: Path | None = None
    try:
        if direction == "up":
            # Pre-clean (untimed, guarded) so a repeat isn't "already there".
            if target_root.exists():
                guard.safe_rmtree(target_root, action="pre-clean robocopy target")
            rc, out, err, seconds = _robocopy(dataset_dir, target_root, mt, transfer_timeout)
        elif direction == "down":
            if dest_dir is None:
                raise ValueError("dest_dir required for 'down' direction")
            # Untimed seed: make sure target_root has the dataset. A failed
            # seed means the timed "download" would move nothing.
            seed_rc, _sout, seed_err, _sec = _robocopy(dataset_dir, target_root, mt, seed_timeout)
            if seed_rc >= ROBOCOPY_FAILURE_THRESHOLD:
                return _failed(f"seed failed: robocopy exit {seed_rc}: {base.tail(seed_err, 500)}")
            # A warm destination makes robocopy skip everything -- empty it.
            guard.empty_dir(dest_dir, action="empty download destination")
            rc, out, err, seconds = _robocopy(target_root, dest_dir, mt, transfer_timeout)
            verify_root = dest_dir
        else:
            return make_skipped(
                ENGINE, dataset_name, direction, params,
                f"unsupported direction for robocopy runner: {direction}", lane, label,
                repeat_index, loopback,
            )
    except guard.DestructiveEndpointRefused as exc:
        return _failed(f"refused: {exc}")
    except Exception as exc:  # subprocess.TimeoutExpired and friends
        return _failed(f"exception: {exc}")

    success = rc < ROBOCOPY_FAILURE_THRESHOLD
    if not success:
        result = _failed(f"robocopy exit {rc}")
        result.seconds = seconds
        result.stderr_tail = base.tail(err)
        return result

    copied = parse_copied_bytes(out)
    if copied is None:
        num_bytes = base.manifest_bytes(dataset_dir)
        bytes_source = "manifest-fallback"
    else:
        num_bytes = copied
        bytes_source = "robocopy-summary"

    expected_bytes = base.manifest_bytes(dataset_dir)
    if bytes_source == "robocopy-summary" and expected_bytes > 0 and num_bytes == 0:
        result = _failed("robocopy copied 0 bytes -- nothing was moved, timing is meaningless")
        result.seconds = seconds
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
            # "up": compare the target listing against the manifest instead of
            # trusting robocopy's exit code.
            manifest = base.manifest_files(dataset_dir)
            verified, detail = _verify_target_sizes(manifest, target_root)
            verify_method = "remote-size-listing"
            if not verified:
                extra_reason = detail

    return RunResult(
        engine=ENGINE,
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
        endpoint=label,
        repeat_index=repeat_index,
        bytes_source=bytes_source,
        verify_method=verify_method,
        loopback=loopback,
    )


def _verify_target_sizes(manifest: list[dict[str, Any]], target_root: Path) -> tuple[bool, str]:
    """Size-listing check of an uploaded tree (no re-download, no hashing)."""
    missing: list[str] = []
    wrong_size: list[str] = []
    try:
        for record in manifest:
            dest = target_root / record["path"]
            if not dest.exists():
                missing.append(record["path"])
            elif dest.stat().st_size != record["size"]:
                wrong_size.append(record["path"])
    except OSError as exc:
        return False, f"could not list upload target: {exc}"
    if missing or wrong_size:
        return False, (
            f"upload listing mismatch: {len(missing)} missing, {len(wrong_size)} wrong size"
        )
    return True, f"listed {len(manifest)} file(s) at the target"


def cleanup_endpoint(endpoint: dict[str, Any], dataset_name: str, direction: str) -> None:
    """Remove the seeded/uploaded scratch subtree, once, after the matrix."""
    guard.safe_rmtree(_target_root(endpoint, dataset_name, direction), action="cleanup robocopy target")
