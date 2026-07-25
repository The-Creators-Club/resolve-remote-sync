"""Scratch-path guard for every destructive call the harness makes.

The bench harness deletes things: `rclone purge <remote_root>` (pre-clean
before a timed upload, plus end-of-matrix cleanup), `shutil.rmtree` of the
robocopy target and of the local download destination. Every one of those
targets is derived from `bench.toml` -- and the example config points at
`Creators_Club/_bench`, i.e. **one edit away from the live project tree**.

So: nothing in this package deletes anything unless the target path carries a
`_bench` component (`SCRATCH_MARKER`). A path like
`Creators_Club/_bench/large/up` is fine; `Creators_Club/2026/CCT` is refused
with `DestructiveEndpointRefused` and the run is recorded as failed rather
than silently proceeding.

The single escape hatch is explicit and operator-supplied:
`ccbench run --allow-destructive-endpoint` (or
`[general] allow_destructive_endpoint = true`), which flips the module-level
override via `set_allow_destructive()`.

Path extraction understands rclone remote specs, because that is what gets
handed to `rclone purge`:

    ":sftp,host=h,key_file=C:\\k:Creators_Club/_bench/large/up"  -> path after the FINAL ':'
    "nas:Creators_Club/_bench/large/up"                          -> path after the FIRST ':'
    "E:\\scratch\\_bench\\large\\up"                              -> the whole string

Deliberately conservative: anything it cannot confidently parse is treated as
"no scratch marker found", i.e. refused.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

SCRATCH_MARKER = "_bench"

_WINDOWS_ABS = re.compile(r"^[A-Za-z]:[\\/]")
_SEPARATORS = re.compile(r"[\\/]+")


class DestructiveEndpointRefused(RuntimeError):
    """Raised instead of deleting a path that carries no `_bench` component."""


_allow_destructive = False


def set_allow_destructive(enabled: bool) -> None:
    """Enable/disable the --allow-destructive-endpoint override (process-wide)."""
    global _allow_destructive
    _allow_destructive = bool(enabled)


def destructive_allowed() -> bool:
    return _allow_destructive


def remote_path_part(target: str | Path) -> str:
    """The filesystem-path portion of a local path or an rclone remote spec."""
    text = str(target)
    if text.startswith(":"):
        # on-the-fly connection string ":backend,params:path" -- the path is
        # always last, so the final ':' delimits it even when a parameter
        # value contains one (key_file=C:\Users\...).
        return text.rsplit(":", 1)[-1]
    if _WINDOWS_ABS.match(text):
        return text
    if ":" in text:
        # named remote "remote:path"
        return text.split(":", 1)[1]
    return text


def path_components(target: str | Path) -> list[str]:
    parts = _SEPARATORS.split(remote_path_part(target))
    return [p for p in parts if p not in ("", ".")]


def is_scratch_path(target: str | Path) -> bool:
    """True iff some component of the target path contains `_bench`."""
    return any(SCRATCH_MARKER in part.lower() for part in path_components(target))


def assert_scratch_path(target: str | Path, *, action: str = "delete") -> None:
    """Refuse `action` on `target` unless it is a scratch path (or overridden)."""
    if is_scratch_path(target):
        return
    if _allow_destructive:
        return
    raise DestructiveEndpointRefused(
        f"refusing to {action} {target!r}: no {SCRATCH_MARKER!r} component in the path. "
        f"Point the endpoint at a scratch subtree (e.g. .../{SCRATCH_MARKER}) or re-run with "
        f"--allow-destructive-endpoint if you really mean it."
    )


def safe_rmtree(path: str | Path, *, action: str = "rmtree") -> None:
    """`shutil.rmtree(ignore_errors=True)`, but only on a scratch path."""
    target = Path(path)
    assert_scratch_path(target, action=action)
    shutil.rmtree(target, ignore_errors=True)


def empty_dir(path: str | Path, *, action: str = "empty destination") -> None:
    """Make `path` an existing, empty directory (guarded).

    Used before every timed download: a warm destination makes rclone/robocopy
    skip files that are already there, so the run would measure nothing.
    """
    target = Path(path)
    if target.exists():
        assert_scratch_path(target, action=action)
        shutil.rmtree(target, ignore_errors=True)
    target.mkdir(parents=True, exist_ok=True)
