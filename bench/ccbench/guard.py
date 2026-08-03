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

One more thing lives here because every destructive call routes through it:
`redact()`. An rclone on-the-fly spec carries the credential inline
(`:smb,host=h,user=u,pass=<obscured>:share/path`), and `rclone reveal` turns
that back into the plaintext password -- so a refusal message quoting the
target verbatim would put a reversible credential into `results.jsonl` and the
rendered report. Every message this module raises is redacted; so is anything
else that puts a remote spec on a result row.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

SCRATCH_MARKER = "_bench"

_WINDOWS_ABS = re.compile(r"^[A-Za-z]:[\\/]")
_SEPARATORS = re.compile(r"[\\/]+")

# rclone connection-string parameters that must never be echoed. Values are
# base64-ish (obscured passwords) or paths, and never contain ',' or ':' -- the
# two characters that delimit a connection string.
_SECRET_PARAM_RE = re.compile(
    r"\b(pass|password|pass2|key_pem|api_key|token|secret_access_key|client_secret)=[^,:]*",
    re.IGNORECASE,
)

REDACTED = "***"


class DestructiveEndpointRefused(RuntimeError):
    """Raised instead of deleting a path that carries no `_bench` component."""


class CleanupFailed(RuntimeError):
    """A pre-clean/empty step could not be proven to have worked.

    Not the same as a refusal: the guard allowed the delete, the delete itself
    didn't happen (a timed-out `rclone purge`, an `rmtree(ignore_errors=True)`
    that left a locked file behind). Callers must fail the run instead of
    timing a transfer into a warm destination.
    """


def redact(target: str | Path) -> str:
    """`target` with any inline credential replaced by `***`.

    Safe to put in a result row, a log line or the report. `rclone reveal` is
    reversible, so an obscured password is a credential, not a hash.
    """
    return _SECRET_PARAM_RE.sub(lambda m: f"{m.group(1)}={REDACTED}", str(target))


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
        f"refusing to {action} {redact(target)!r}: no {SCRATCH_MARKER!r} component in the path. "
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

    `rmtree(ignore_errors=True)` can leave files behind (a locked handle, a
    permission error) without saying so, which is exactly how a warm
    destination survives into a timed run. So the result is checked and
    `CleanupFailed` is raised if anything is still there -- the caller must
    fail the run rather than measure a partial download.
    """
    target = Path(path)
    if target.exists():
        assert_scratch_path(target, action=action)
        shutil.rmtree(target, ignore_errors=True)
    target.mkdir(parents=True, exist_ok=True)
    leftovers = [p.name for p in target.iterdir()]
    if leftovers:
        raise CleanupFailed(
            f"could not {action} {redact(target)!r}: {len(leftovers)} entry/entries survived "
            f"the delete (e.g. {leftovers[:3]}). Timing a transfer into a warm destination "
            f"measures nothing."
        )
