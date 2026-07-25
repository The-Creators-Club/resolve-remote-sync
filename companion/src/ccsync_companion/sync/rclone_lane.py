"""Lane A (video originals, editor -> NAS) and Lane B (proxies, NAS -> editor).

Both lanes wrap the same rclone-subprocess machinery (SPEC.md: "sync/rclone_
lane.py — wraps an rclone subprocess"); only the filter rules, rclone
subcommand (copy vs sync), direction, and trigger (watchdog+periodic vs
periodic-only) differ, so one module + one class parameterized by
`direction` covers both.

Filter-rule correctness (especially Lane B's nested-Proxy-dir selection) was
verified against a real rclone binary with --dry-run against local fixture
dirs before writing this — see tests/test_rclone_filters.py, which re-proves
it in CI. rclone's directory-filter semantics are subtle: a bare "- **" at
the end of a filter list does NOT, by itself, stop rclone from *listing*
directories to look for matches inside them, but an explicit "+ **/Proxy/"
directory-allow rule is still included below for clarity and for parity
with `rclone check`/`ncdu`-style tools that do prune eagerly.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from .base import (
    STATE_ERROR,
    STATE_IDLE,
    STATE_SYNCING,
    LaneAdapter,
    LaneStatus,
)

log = logging.getLogger("ccsync.sync.rclone")

VIDEO_EXTS = [
    ".braw", ".mov", ".mp4", ".mxf", ".avi", ".mts", ".m2ts", ".mkv",
    ".r3d", ".crm", ".mpg", ".mpeg", ".wmv", ".webm", ".insv", ".360",
]

DIRECTION_UP = "up"
DIRECTION_DOWN = "down"

# Lane B is `rclone sync`, i.e. the one verb in this system that removes
# local files. Every such removal is turned into a MOVE into this directory
# under local_root (--backup-dir), so nothing lane B does is unrecoverable
# (AUDIT_2 DEL-2). It has to live under local_root to stay on the same
# filesystem (a cross-volume backup-dir turns a rename into a full copy),
# and rclone refuses a backup-dir that overlaps the destination UNLESS the
# filter excludes it -- hence TRASH_EXCLUDE_RULE below, which is why that
# rule must be FIRST in the lane B rule list (rclone filters are
# first-match-wins). Verified against the bundled rclone 1.74.4: with the
# rule, deletes become "Moved into backup dir"; without it, rclone aborts
# with "destination and parameter to --backup-dir mustn't overlap".
TRASH_DIR_NAME = ".ccsync-trash"
TRASH_EXCLUDE_RULE = f"- /{TRASH_DIR_NAME}/**"

# Blast-radius bound on lane B's sync (AUDIT_2 §4.2 safety row). Measured:
# rclone stops deleting once the cap is hit and exits non-zero, and under
# --dry-run it caps the reported `deletes` count -- which can only ever turn
# a large number into a smaller non-zero one, so consolidate.py's
# "would this delete anything?" guard cannot be blinded by it.
LANE_B_MAX_DELETE = "100"
LANE_B_MAX_DELETE_SIZE = "20G"

# rclone's exit code for "--max-duration reached" (measured against the
# bundled 1.74.4: 10, NOT the 7 that means a fatal error such as tripping
# --max-delete). A bounded stop is a clean end of a per-project budget, not
# a lane failure, so it must not paint the lane red.
RCLONE_EXIT_MAX_DURATION = 10

# How many stderr lines of a periodic run are retained (the TAIL). rclone
# with --use-json-log --verbose emits a record per file, so keeping the whole
# stream to re-parse at the end held hundreds of MB in the companion's RSS
# during a big ingest (AUDIT_3 M-8). The counting happens incrementally
# (RcloneRunTally); this is only what a human/last_error needs to see.
STDERR_TAIL_LINES = 200

# -- transport tuning (AUDIT_2 §4.1 P1/P2, §4.2 table) ---------------------
#
# Every value below is a DEFAULT, overridable per-key from config.toml via
# RcloneTuning.from_cfg (AUDIT_2 C-5: bench results must be applyable rather
# than hardcoded). Defaults verified against the bundled rclone 1.74.4 --
# `rclone help flags` reports --sftp-chunk-size default 32Ki,
# --sftp-concurrency default 64, --checkers default 8, --sftp-connections
# default 0 (unlimited).
#
# P1, the big one: rclone has no multi-thread UPLOAD for sftp, so one file
# rides one SSH stream whose in-flight window is chunk_size x concurrency.
# 32Ki x 64 = 2 MiB, i.e. a per-file ceiling of ~14 MB/s at 150 ms RTT --
# which is exactly the ~60 mb/s class this project exists to beat. 255Ki is
# the largest chunk the SFTP protocol's 256 KiB total packet allows.
DEFAULT_SFTP_CHUNK_SIZE = "255Ki"
# Left at rclone's own default deliberately: memory is
# chunk x concurrency x streams, so 255Ki paired with 256 would be 64 MiB
# per stream. 255Ki x 64 = 16.3 MiB is the intended window.
DEFAULT_SFTP_CONCURRENCY = 64
# Caps rclone's SSH connection pool so wider checkers/transfers cannot trip
# TrueNAS sshd's MaxStartups 10:30:100.
DEFAULT_SFTP_CONNECTIONS = 16
DEFAULT_CHECKERS = 16
# P2: rclone verifies size AND hash after every transfer when a common hash
# exists, and the SFTP backend gets MD5 by shelling `md5sum <path>` over SSH
# (rclone.conf sets shell_type = unix) -- so the NAS re-reads the whole file
# it just received. Measured against the bundled binary: a copy logs
# "big.mov: md5 = ... OK" and that line disappears under --ignore-checksum.
#
# TRADE-OFF, stated explicitly: end-to-end post-copy verification drops to
# size-only. --ignore-checksum is chosen over --sftp-disable-hashcheck
# because it removes the same full-file re-read while KEEPING hash-based
# comparison available to rclone (checks, dedupe, future --checksum runs);
# disabling the backend's hash support removes the capability outright.
# SSH already MACs every packet on the wire and ZFS checksums at rest, so
# the belt lost here is the third one, not the first.
DEFAULT_IGNORE_CHECKSUM = True
# Lane A: newest first -- the clip the team is waiting on goes before the
# archive backlog. Lane B: smallest first -- an editor gets many usable
# proxies sooner on a cold project.
DEFAULT_ORDER_BY_UP = "modtime,descending"
DEFAULT_ORDER_BY_DOWN = "size,ascending"

# NOT added, deliberately (AUDIT_2 §4.2 measured these):
#   --fast-list           no-op, SFTP has no ListR
#   --use-server-modtime  no-op for SFTP
#   --no-traverse         a PESSIMISATION on a full pass (measured: 61 dir
#                         modtime setstats vs 2). Only ever valid paired
#                         with --no-update-dir-modtime on an express run.

# -- lane A stability gate -------------------------------------------------
#
# 120s, not SPEC's 30s: Windows CopyFile, Explorer, shutil.copy2 and every
# card-ingest tool PRESERVE the source mtime, so a 40 GB .braw satisfies
# --min-age 30s from the instant it appears (AUDIT_2 L-14). Shared by the
# periodic pass (--min-age) and the express path, which enforces the same
# age in Python -- see build_express_command for why it cannot use the flag.
LANE_A_MIN_AGE_SECONDS = 120
LANE_A_MIN_AGE = f"{LANE_A_MIN_AGE_SECONDS}s"

# -- express lane A (AUDIT_2 C-2 / P9) -------------------------------------
EXPRESS_DEFAULT_ENABLED = True
# Batch cap. Beyond this the batch is dropped and the periodic full pass --
# which is never replaced, only supplemented -- picks the files up. A card
# ingest fires thousands of on_modified events a minute; express is for the
# "editor drops a clip in" case, not for shovelling a whole card.
EXPRESS_DEFAULT_MAX_BATCH = 200
# A pending path that has never become eligible within this long is handed
# back to the periodic pass rather than re-stat'd forever.
EXPRESS_PENDING_MAX_SECONDS = 1800.0
# How old an express list file must be before a lane start treats it as
# debris from a hard kill. Comfortably longer than any express run.
EXPRESS_LIST_STALE_SECONDS = 86400.0


def _cfg_str(cfg: Optional[dict], key: str, default: str) -> str:
    if not cfg:
        return default
    raw = cfg.get(key, default)
    return "" if raw is None else str(raw).strip()


def _cfg_int(cfg: Optional[dict], key: str, default: int) -> int:
    if not cfg:
        return default
    try:
        return int(cfg.get(key, default))
    except (TypeError, ValueError):
        log.warning("rclone tuning: %s=%r is not an integer -- using %d", key, cfg.get(key), default)
        return default


@dataclass(frozen=True)
class RcloneTuning:
    """Per-lane transport tuning. Every field disables its flag when set to
    "" (strings) or 0 (ints), so an operator can revert any single knob from
    config.toml without a code change."""

    sftp_chunk_size: str = DEFAULT_SFTP_CHUNK_SIZE
    sftp_concurrency: int = DEFAULT_SFTP_CONCURRENCY
    sftp_connections: int = DEFAULT_SFTP_CONNECTIONS
    checkers: int = DEFAULT_CHECKERS
    ignore_checksum: bool = DEFAULT_IGNORE_CHECKSUM
    order_by_up: str = DEFAULT_ORDER_BY_UP
    order_by_down: str = DEFAULT_ORDER_BY_DOWN

    @classmethod
    def from_cfg(cls, cfg: Optional[dict]) -> "RcloneTuning":
        if not cfg:
            return cls()
        return cls(
            sftp_chunk_size=_cfg_str(cfg, "sftp_chunk_size", DEFAULT_SFTP_CHUNK_SIZE),
            sftp_concurrency=_cfg_int(cfg, "sftp_concurrency", DEFAULT_SFTP_CONCURRENCY),
            sftp_connections=_cfg_int(cfg, "sftp_connections", DEFAULT_SFTP_CONNECTIONS),
            checkers=_cfg_int(cfg, "checkers", DEFAULT_CHECKERS),
            ignore_checksum=bool(cfg.get("rclone_ignore_checksum", DEFAULT_IGNORE_CHECKSUM)),
            order_by_up=_cfg_str(cfg, "order_by_up", DEFAULT_ORDER_BY_UP),
            order_by_down=_cfg_str(cfg, "order_by_down", DEFAULT_ORDER_BY_DOWN),
        )

    def flags(self, direction: str) -> list[str]:
        flags: list[str] = []
        if self.sftp_chunk_size:
            flags += ["--sftp-chunk-size", self.sftp_chunk_size]
        if self.sftp_concurrency > 0:
            flags += ["--sftp-concurrency", str(self.sftp_concurrency)]
        if self.sftp_connections > 0:
            flags += ["--sftp-connections", str(self.sftp_connections)]
        if self.checkers > 0:
            flags += ["--checkers", str(self.checkers)]
        if self.ignore_checksum:
            flags.append("--ignore-checksum")
        order_by = self.order_by_up if direction == DIRECTION_UP else self.order_by_down
        if order_by:
            flags += ["--order-by", order_by]
        return flags


def _win_creationflags() -> int:
    """CREATE_NO_WINDOW: rclone is spawned from a windowed (console=False,
    build.spec) build, so without this every lane run and every
    rclone_available() probe flashes a fresh black console window on the
    editor's desktop. upgrade.py's _default_spawn applies the same flag for
    the self-upgrade spawn -- mirrored here. A no-op (0) off Windows."""
    if sys.platform == "win32":
        return subprocess.CREATE_NO_WINDOW
    return 0


def build_filter_rules_up() -> list[str]:
    """Lane A: video files anywhere EXCEPT under a Proxy/ dir, nothing else.

    Both the nested (`**/Proxy/**`) and root-level (`/Proxy/**`) forms are
    needed: rclone's `**/` requires at least one leading path component, so
    a Proxy/ dir at the tree root would slip past the nested rule alone.
    """
    rules = ["- **/Proxy/**", "- /Proxy/**"]
    rules += [f"+ *{ext}" for ext in VIDEO_EXTS]
    rules.append("- **")
    return rules


def build_filter_rules_down() -> list[str]:
    """Lane B: only the contents of Proxy/ dirs, at any depth (root included).

    The trash exclude comes FIRST (first-match-wins): the backup dir mirrors
    the source layout, so `.ccsync-trash/<ts>/Sub/Proxy/x.mov` matches
    `**/Proxy/**` and would otherwise be both re-deleted every pass and
    rejected by rclone's backup-dir overlap check.
    """
    return [
        TRASH_EXCLUDE_RULE,
        "+ /Proxy/",
        "+ /Proxy/**",
        "+ **/Proxy/",
        "+ **/Proxy/**",
        "- **",
    ]


class FilterFileError(RuntimeError):
    """The lane's filter file is missing, empty, or doesn't end in `- **`.

    A lane B run with an empty filter file is `rclone sync` with no filter
    at all: measured, that deletes every local file the NAS lacks, including
    camera originals still queued for lane A (AUDIT_2 DEL-2). Refusing to
    build the command is the only safe response.
    """


def validate_filter_file(path: Path) -> None:
    """Raise FilterFileError unless `path` holds a usable filter list.

    Guards the cross-process race DEL-2 describes: two companions sharing
    ~/.ccsync/state/filter_down.txt, one truncating it while the other's
    rclone parses it. write_filter_file() below closes the write half
    (tmp + os.replace); this closes the read half.
    """
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        raise FilterFileError(f"filter file unreadable ({path}): {exc}") from exc
    rules = [line.strip() for line in text.splitlines() if line.strip()]
    if not rules:
        raise FilterFileError(f"filter file is empty ({path}) -- refusing to run unfiltered")
    if rules[-1] != "- **":
        raise FilterFileError(
            f"filter file's last rule is {rules[-1]!r}, not '- **' ({path}) -- "
            "refusing to run with an incomplete filter"
        )


def write_filter_file(rules: list[str], path: Path) -> Path:
    """Write the rule list ATOMICALLY (tmp file + os.replace).

    Path.write_text truncates first, leaving the file at zero bytes for the
    duration of the write -- and rclone reads --filter-from exactly once at
    startup. A second companion process (self-upgrade spawns the new exe
    before the old one exits) rewriting this same fixed path in that window
    handed the other process's rclone an empty filter (AUDIT_2 DEL-2).
    os.replace is atomic on both Windows and posix, so a reader either sees
    the whole old file or the whole new one.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "\n".join(rules) + "\n"
    # PID in the temp name: two processes racing here must not share a tmp.
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    try:
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise
    return path


# Successful `rclone version` probes are cached for this long, per path.
# run_once() probes on EVERY call, so a 6-project pass spawned ~12 extra
# processes (each one a window-suppressed CreateProcess + binary load) purely
# to re-learn that the binary that was there 200 ms ago is still there
# (AUDIT_2 §4.2, last rows). Only SUCCESSES are cached: a missing/broken
# binary must be re-probed every time so the lane recovers the instant it is
# installed or repaired, and so the error stays truthful.
RCLONE_PROBE_TTL_SECONDS = 300.0
_rclone_probe_cache: dict[str, tuple[float, str]] = {}
_rclone_probe_lock = threading.Lock()


def reset_rclone_available_cache() -> None:
    """Drop every cached probe result (self-upgrade replaced the binary,
    tests, or a config change repointing rclone_path)."""
    with _rclone_probe_lock:
        _rclone_probe_cache.clear()


def rclone_available(rclone_path: str, use_cache: bool = True) -> tuple[bool, str]:
    """Check whether `rclone_path` resolves to a runnable rclone binary.

    Returns (available, message). Never raises.
    """
    if use_cache:
        with _rclone_probe_lock:
            entry = _rclone_probe_cache.get(rclone_path)
        if entry is not None and (time.monotonic() - entry[0]) < RCLONE_PROBE_TTL_SECONDS:
            return True, entry[1]

    resolved = rclone_path
    if not os.path.isabs(rclone_path):
        found = shutil.which(rclone_path)
        if found is None:
            return False, f"rclone not found on PATH ('{rclone_path}')"
        resolved = found
    elif not os.path.exists(resolved):
        return False, f"rclone not found at '{resolved}'"

    try:
        proc = subprocess.run(
            [resolved, "version"],
            capture_output=True,
            timeout=10,
            encoding="utf-8",
            errors="replace",
            creationflags=_win_creationflags(),
        )
    except Exception as exc:
        return False, f"rclone at '{resolved}' failed to run: {exc}"
    if proc.returncode != 0:
        return False, f"rclone at '{resolved}' exited {proc.returncode}"
    with _rclone_probe_lock:
        _rclone_probe_cache[rclone_path] = (time.monotonic(), resolved)
    return True, resolved


def _join_remote_path(remote_root: str, subpath: str) -> str:
    """Join a remote root and a posix-style subpath with exactly one '/'
    between them, regardless of leading/trailing slashes on either side."""
    root = remote_root.rstrip("/")
    sub = subpath.strip("/")
    if not root:
        return sub
    if not sub:
        return root
    return f"{root}/{sub}"


def _run_lsf(cmd: list[str], timeout: float) -> Optional[str]:
    proc = subprocess.run(
        cmd,
        capture_output=True,
        timeout=timeout,
        encoding="utf-8",
        errors="replace",
        creationflags=_win_creationflags(),
    )
    if proc.returncode != 0:
        log.warning(
            "rclone lsf exited %d: %s", proc.returncode, (proc.stderr or "").strip()[:300]
        )
        return None
    return proc.stdout


def clone_directory_tree(
    rclone_path: str,
    remote: str,
    remote_root: str,
    local_root: str,
    subpath: str,
    run_fn: Optional[Callable[[list[str], float], Optional[str]]] = None,
    timeout: float = 300.0,
) -> Optional[int]:
    """Replicate the NAS-side DIRECTORY STRUCTURE of `subpath` under
    local_root -- every directory, including empty ones.

    Exists because nothing else carries empty dirs to an editor: lane B's
    filters copy proxy FILES only (rclone never creates a directory no
    matching file lives in), and lane C's editor-side .stignore drops video
    files and Proxy dirs -- so a project's empty scaffolding (folders the
    team laid out but hasn't filled yet) never appears on an editor's
    machine. One `rclone lsf --dirs-only -R` listing + local mkdirs;
    deliberately NOT an rclone sync with --create-empty-src-dirs, whose
    interaction with filter rules is subtle (see module docstring).

    Returns the number of directories newly created, or None when the
    listing failed (misconfigured remote, network down). Never raises.
    """
    if not remote or not remote_root:
        return None
    remote_side = f"{remote}:{_join_remote_path(remote_root, subpath)}"
    cmd = [
        rclone_path, "lsf", "--dirs-only", "-R", remote_side,
        # Prune the two dot-trees that dominate a NAS listing: .stversions
        # accumulates a deep mirror of every deleted file's directory
        # structure, so listing it costs real time over SFTP for entries we
        # must never recreate anyway (AUDIT_2 DEL-1 / C-3).
        "--exclude", ".stversions/**",
        "--exclude", ".stfolder/**",
    ]
    runner = run_fn or _run_lsf
    try:
        output = runner(cmd, timeout)
    except Exception as exc:
        log.warning("structure clone: rclone lsf failed for %s: %s", remote_side, exc)
        return None
    if output is None:
        return None

    local_sub = _local_subpath(subpath)
    base = Path(local_root) / local_sub if local_sub else Path(local_root)
    created = 0
    try:
        if not base.is_dir():
            base.mkdir(parents=True, exist_ok=True)
            created += 1
    except OSError as exc:
        log.warning("structure clone: could not create %s: %s", base, exc)
        return None
    for line in output.splitlines():
        rel = line.strip().strip("/")
        # lsf never emits absolute or parent-relative entries, but a mkdir
        # escaping local_root would be bad enough to guard anyway.
        if not rel or ".." in Path(rel).parts or Path(rel).is_absolute():
            continue
        # NEVER recreate a dot-directory. `.stfolder` is Syncthing's folder
        # marker: its ABSENCE is the only thing that turns "the local folder
        # is missing/empty" into a stopped folder with an error instead of
        # "the user deleted 5,000 files -- propagate that to the NAS and to
        # every other editor". Recreating it here converted a recoverable
        # mistake (an editor moving/renaming their project dir, a stale
        # empty mount point) into a mass delete (AUDIT_2 DEL-1). `.stversions`
        # is the server's versioned trash skeleton -- equally not ours to
        # mirror. Guarding the whole `.`-prefixed class rather than two
        # names keeps `.stignore`, `.syncthing.*` and anything Syncthing
        # adds later on the safe side by default.
        segments = [seg for chunk in rel.split("/") for seg in chunk.split("\\") if seg]
        if any(seg.startswith(".") for seg in segments):
            continue
        target = base / rel
        try:
            if not target.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                created += 1
        except OSError as exc:
            log.warning("structure clone: could not create %s: %s", target, exc)
    return created


# rclone's default --inplace=false writes to "<name>.partial" and renames on
# completion, so a killed lane A leaves one behind -- and lane A never
# deletes, so they accumulate on the NAS forever (AUDIT_2 P8/P15).
PARTIAL_SUFFIX = ".partial"

# The express run's own partial suffix, and this one is load-bearing rather
# than cosmetic. Measured against the bundled 1.74.4: the temp name is
# `<name>.<token>.partial` where <token> is DERIVED FROM THE FILE, not random
# per run -- two separate runs produced `clip1.mov.42048420.partial` both
# times. So the express run and the periodic pass uploading the same new file
# at the same time would write the SAME temp path and interleave into a
# corrupt result. A distinct suffix gives them disjoint temp names; both then
# rename a COMPLETE file into place and last-writer-wins is harmless because
# the bytes are identical. Must stay <= 16 chars (rclone rejects longer) and
# must still end in `.partial` so scan_orphan_partials keeps finding them.
EXPRESS_PARTIAL_SUFFIX = ".exp.partial"


def scan_orphan_partials(
    rclone_path: str,
    remote: str,
    remote_root: str,
    subpath: Optional[str] = None,
    run_fn: Optional[Callable[[list[str], float], Optional[str]]] = None,
    timeout: float = 120.0,
    max_samples: int = 20,
) -> Optional[dict]:
    """Count/size the orphan `*.partial` files left on the NAS under
    `subpath`. REPORTS ONLY -- deliberately never deletes.

    AUDIT_2 C-7 is explicit about this: cleaning them up would be the one
    performance suggestion that adds a delete-on-NAS path, and the
    never-delete requirement outranks the disk-hygiene gain. So this returns
    a payload someone can look at and act on by hand.

    Returns {"count", "bytes", "samples"} or None when the listing failed.
    Never raises.
    """
    if not remote or not remote_root:
        return None
    remote_side = f"{remote}:{_join_remote_path(remote_root, subpath or '')}"
    cmd = [
        rclone_path, "lsf", "-R", "--files-only",
        "--format", "sp", "--separator", ";",
        # --filter, not --include + --exclude: measured against the bundled
        # 1.74.4, mixing the two makes rclone warn that "the order they are
        # parsed in is indeterminate". First-match-wins filter rules are
        # unambiguous -- prune the dot-trees, keep partials, drop the rest.
        "--filter", "- .stversions/**",
        "--filter", "- .stfolder/**",
        "--filter", f"+ *{PARTIAL_SUFFIX}",
        "--filter", "- **",
        remote_side,
    ]
    runner = run_fn or _run_lsf
    try:
        output = runner(cmd, timeout)
    except Exception as exc:
        log.debug("orphan .partial scan failed for %s: %s", remote_side, exc)
        return None
    if output is None:
        return None

    count = 0
    total = 0
    samples: list[dict] = []
    for line in output.splitlines():
        line = line.strip()
        if not line:
            continue
        size_text, _, name = line.partition(";")
        if not name:
            continue
        try:
            size = int(size_text)
        except ValueError:
            size = -1
        count += 1
        if size > 0:
            total += size
        if len(samples) < max_samples:
            samples.append({"name": name, "bytes": size})
    return {"count": count, "bytes": total, "samples": samples}


def scan_trash_dir(local_root: str, max_entries: int = 50000) -> Optional[dict]:
    """Count/size `<local_root>/.ccsync-trash` -- lane B's recovery copies.

    Same rule as the partials: reported, never pruned (deleting the recovery
    copy defeats its entire purpose). Bounded by `max_entries` so a huge
    trash tree can't turn a status read into a multi-minute walk."""
    base = Path(local_root) / TRASH_DIR_NAME
    if not base.is_dir():
        return {"count": 0, "bytes": 0, "truncated": False}
    count = 0
    total = 0
    truncated = False
    try:
        for dirpath, _dirnames, filenames in os.walk(base):
            for name in filenames:
                if count >= max_entries:
                    truncated = True
                    break
                count += 1
                try:
                    total += os.path.getsize(os.path.join(dirpath, name))
                except OSError:
                    pass
            if truncated:
                break
    except OSError as exc:
        log.debug("trash scan failed for %s: %s", base, exc)
        return None
    return {"count": count, "bytes": total, "truncated": truncated}


def _append_stats_flags(cmd: list[str], stats_interval: Optional[str]) -> list[str]:
    if stats_interval:
        cmd += ["--stats", stats_interval, "--stats-log-level", "NOTICE"]
    return cmd


def _transport_flags() -> list[str]:
    """Bounds on a stalled peer, shared by both lanes.

    rclone's own idle default already covers most cases, but a peer that
    ACKs and then stalls (a Tailscale DERP flap, a hung TrueNAS SFTP
    subsystem) can otherwise hold _run_lock -- and therefore the whole
    sequencer -- forever (AUDIT_2 L-12). --retries-sleep stops a hot retry
    loop burning a whole pass while the tailnet flaps (§4.2)."""
    return [
        "--timeout", "5m",
        "--contimeout", "60s",
        "--retries-sleep", "10s",
    ]


def _max_duration_flags(max_duration_seconds: Optional[float]) -> list[str]:
    """Per-project time budget (AUDIT_2 L-4).

    SOFT cutoff deliberately: the HARD default aborts the in-flight
    transfer, and since SFTP uploads don't resume, a 40 GB original killed
    at 39 GB restarts from byte 0 next pass and leaves a `.partial` on the
    NAS that nothing ever cleans up. SOFT stops STARTING new transfers and
    lets the current one land. Measured exit code either way: 10."""
    if not max_duration_seconds or max_duration_seconds <= 0:
        return []
    return ["--max-duration", f"{int(max_duration_seconds)}s", "--cutoff-mode", "SOFT"]


def _local_subpath(subpath: str | None) -> str | None:
    """Strip leading/trailing path separators from `subpath` before it is
    joined onto local_root: pathlib treats a rooted component (leading "/"
    or "\\") as absolute, so `Path(local_root) / "/Projects/x"` silently
    discards local_root entirely and joins onto the filesystem root
    instead. The remote side doesn't need this -- _join_remote_path already
    strips slashes on both sides of its own join."""
    if not subpath:
        return subpath
    stripped = subpath.strip("/\\")
    return stripped or None


def build_up_command(
    rclone_path: str,
    local_root: str,
    remote: str,
    remote_root: str,
    filter_file: Path,
    transfers: int = 4,
    subpath: str | None = None,
    stats_interval: str | None = None,
    max_duration_seconds: float | None = None,
    tuning: Optional[RcloneTuning] = None,
) -> list[str]:
    validate_filter_file(filter_file)
    tuning = tuning if tuning is not None else RcloneTuning()
    local_sub = _local_subpath(subpath)
    local_side = str(Path(local_root) / local_sub) if local_sub else str(local_root)
    remote_side = (
        f"{remote}:{_join_remote_path(remote_root, subpath)}" if subpath else f"{remote}:{remote_root}"
    )
    cmd = [
        rclone_path,
        "copy",
        local_side,
        remote_side,
        "--filter-from", str(filter_file),
        "--ignore-existing",
        "--ignore-case",  # rclone filters are case-sensitive by default;
        # without this, uppercase camera extensions (CLIP.MOV) and a
        # lowercase-cased "proxy/" dir slip past the filter rules entirely.
        # LANE_A_MIN_AGE is 120s, not SPEC's 30s -- see the constant. rclone
        # does catch a mid-write read (hash mismatch, .partial removed), but
        # only after wasting the whole transfer upstream and painting the
        # lane red with "corrupted on transfer" (AUDIT_2 L-14).
        "--min-age", LANE_A_MIN_AGE,
        "--transfers", str(transfers),
        *tuning.flags(DIRECTION_UP),
        *_transport_flags(),
        *_max_duration_flags(max_duration_seconds),
        "--use-json-log",
        "--verbose",  # INFO-level per-file log lines — parse_json_log() needs these
    ]
    return _append_stats_flags(cmd, stats_interval)


def path_matches_lane_a_filter(path: str) -> bool:
    """Python re-implementation of build_filter_rules_up() + --ignore-case,
    for a single path.

    The express run CANNOT pass the filter file to rclone (see
    build_express_command), so this predicate is the only thing standing
    between a watchdog event and the upload. It must stay equivalent to the
    rule list: a video extension, and no `Proxy` component at any depth --
    both case-insensitively, which is what --ignore-case buys the real run.
    test_rclone_filters.py proves the equivalence against the real binary.
    """
    if not path:
        return False
    if os.path.splitext(path)[1].lower() not in VIDEO_EXTS:
        return False
    parts = [seg for chunk in str(path).split("/") for seg in chunk.split("\\")]
    return not any(seg.lower() == "proxy" for seg in parts)


class ExpressListError(RuntimeError):
    """The express run's --files-from-raw list is empty or holds an entry
    rclone would misread. Measured against the bundled 1.74.4: a blank line
    in a raw list is read as the ROOT directory and the run dies with
    "Failed to copy: is a directory not a file" (exit 1), and a backslash-
    separated entry silently matches nothing at all (0 B transferred,
    exit 0) -- a silent no-op is the worse of the two."""


def write_files_from_list(rels: list[str], path: Path) -> Path:
    """Write an express `--files-from-raw` list ATOMICALLY (tmp + os.replace).

    Same discipline as write_filter_file, for the same reason (AUDIT_2
    DEL-2): rclone reads the file once at startup, and a truncated read is
    exactly how the audit's worst finding happened. The caller additionally
    gives every run a UNIQUE file name, so two express runs can never read
    each other's list.

    --files-from-raw means "no interpretation at all": no comments, no
    quoting, no blank-line skipping, raw UTF-8 bytes. That is what makes a
    non-ASCII filename survive (measured: `café 日本語.braw` round-trips),
    and it is why every entry is validated here.
    """
    cleaned: list[str] = []
    seen: set[str] = set()
    for raw in rels:
        rel = str(raw).replace("\\", "/").strip().strip("/")
        if not rel:
            raise ExpressListError("express list entry is empty -- rclone reads a blank line as the root dir")
        if "\n" in rel or "\r" in rel:
            raise ExpressListError(f"express list entry contains a newline: {raw!r}")
        segments = [seg for seg in rel.split("/") if seg]
        if any(seg == ".." for seg in segments) or Path(rel).is_absolute() or ":" in segments[0]:
            raise ExpressListError(f"express list entry escapes the local root: {raw!r}")
        if rel in seen:
            continue
        seen.add(rel)
        cleaned.append(rel)
    if not cleaned:
        raise ExpressListError("express list is empty -- refusing to run rclone with a blank list")

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Exactly one trailing newline: a SECOND one is a blank entry, i.e. the
    # root dir (see ExpressListError). newline="" keeps LF on Windows too --
    # CRLF happens to work, but LF is what was measured clean.
    text = "\n".join(cleaned) + "\n"
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    try:
        with open(tmp, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)
        os.replace(tmp, path)
    except OSError:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return path


def build_express_command(
    rclone_path: str,
    local_root: str,
    remote: str,
    remote_root: str,
    list_file: Path,
    transfers: int = 4,
    stats_interval: str | None = None,
    tuning: Optional[RcloneTuning] = None,
) -> list[str]:
    """Express lane A (AUDIT_2 C-2): upload exactly the files the watchdog
    named, now, instead of at the sequencer's next turn for that project.

    UPLOAD-ONLY BY CONSTRUCTION: `copy` (never `sync`, never `move`) plus
    --ignore-existing. It cannot delete, cannot overwrite, and cannot
    truncate anything on either side, which is what makes it safe to run
    CONCURRENTLY with the periodic pass over the same tree -- together with
    --partial-suffix, which keeps the two runs' temp files apart (see
    EXPRESS_PARTIAL_SUFFIX: rclone's partial token is derived from the file,
    so without this they would share one temp path).

    --no-traverse is paired with --no-update-dir-modtime and appears ONLY
    here: unpaired on a full pass it is a pessimisation (AUDIT_2 P10 --
    measured 61 dir-modtime setstats vs 2).

    NO FILTER FLAGS, deliberately, and this is a deviation from C-2's
    literal argv. Measured against the bundled rclone 1.74.4:

        rclone copy ... --files-from-raw list.txt --min-age 120s
        CRITICAL: Failed to initialise global options: failed to reload
        "filter" options: the usage of --files-from-raw overrides all other
        filters, it should be used alone or with --files-from

    The same error comes back for --filter-from. So --min-age AND the lane A
    filter rules are enforced in Python before a path is ever written to the
    list (path_matches_lane_a_filter + the size-stability/min-age gate in
    RcloneLane._express_partition), which is strictly stronger than the
    flags: --min-age alone is not a stability guard for mtime-preserving
    ingests (L-14), the express gate additionally requires two consecutive
    size-stable observations.
    """
    tuning = tuning if tuning is not None else RcloneTuning()
    cmd = [
        rclone_path,
        "copy",
        str(local_root),
        f"{remote}:{remote_root}",
        "--files-from-raw", str(list_file),
        "--no-traverse",
        "--no-update-dir-modtime",
        "--ignore-existing",
        # Disjoint temp names from the periodic pass -- see the constant.
        "--partial-suffix", EXPRESS_PARTIAL_SUFFIX,
        "--transfers", str(transfers),
        *tuning.flags(DIRECTION_UP),
        *_transport_flags(),
        "--use-json-log",
        "--verbose",
    ]
    return _append_stats_flags(cmd, stats_interval)


def build_down_command(
    rclone_path: str,
    local_root: str,
    remote: str,
    remote_root: str,
    filter_file: Path,
    transfers: int = 4,
    subpath: str | None = None,
    stats_interval: str | None = None,
    backup_dir: str | None = None,
    max_duration_seconds: float | None = None,
    tuning: Optional[RcloneTuning] = None,
) -> list[str]:
    """Lane B: `rclone sync` NAS -> editor, proxies only.

    `backup_dir` is how a caller makes this lane's deletions recoverable
    (see TRASH_DIR_NAME) -- RcloneLane always supplies one. It is a
    parameter rather than a default because consolidate.py builds its
    --dry-run argv through here too, and with --backup-dir set rclone logs
    "Skipped move into backup dir" instead of "Skipped delete", which would
    empty the delete-sample list the consent dialog shows the editor. The
    dry run deletes nothing, so it needs no backup dir; the real run, which
    goes through RcloneLane, always gets one.
    """
    validate_filter_file(filter_file)
    tuning = tuning if tuning is not None else RcloneTuning()
    local_sub = _local_subpath(subpath)
    local_side = str(Path(local_root) / local_sub) if local_sub else str(local_root)
    remote_side = (
        f"{remote}:{_join_remote_path(remote_root, subpath)}" if subpath else f"{remote}:{remote_root}"
    )
    cmd = [
        rclone_path,
        "sync",
        remote_side,
        local_side,
        "--filter-from", str(filter_file),
        "--ignore-case",  # see build_up_command -- same case-sensitivity gap
    ]
    if backup_dir:
        cmd += ["--backup-dir", str(backup_dir)]
    cmd += [
        # Bounds the blast radius of a misconfigured remote_root or a
        # remote that transiently lists as empty: rclone stops deleting at
        # the cap instead of clearing the whole proxy set.
        "--max-delete", LANE_B_MAX_DELETE,
        "--max-delete-size", LANE_B_MAX_DELETE_SIZE,
        "--transfers", str(transfers),
        *tuning.flags(DIRECTION_DOWN),
        *_transport_flags(),
        *_max_duration_flags(max_duration_seconds),
        "--use-json-log",
        "--verbose",  # INFO-level per-file log lines — parse_json_log() needs these
    ]
    return _append_stats_flags(cmd, stats_interval)


@dataclass
class RcloneRunResult:
    ok: bool
    transferred: int
    errors: list[str]
    raw_returncode: int
    # How many error lines were SEEN. `errors` itself is bounded on the
    # incremental path (see RcloneRunTally), so len(errors) is not the count.
    error_count: int = 0
    # Whether any file was moved into --backup-dir this run (lane B) -- see
    # RcloneLane._notify_trash.
    deleted: int = 0


class RcloneRunTally:
    """Incremental parse_json_log: same rules, one line at a time.

    The whole stderr stream used to be accumulated in a list and joined at
    the end of the run purely so parse_json_log() could re-parse it. With
    --use-json-log --verbose rclone emits an INFO record PER FILE, so a card
    ingest of a few hundred thousand files held hundreds of MB of JSON in the
    companion's RSS for the length of the run -- on the editor's machine,
    while it was also uploading (AUDIT_3 M-8). Every line is already handed
    to _handle_stderr_line for the live --stats parse, so it is counted
    there instead and only a bounded TAIL is retained for last_error and
    diagnostics."""

    # Enough to explain a failure; the log file has the rest.
    MAX_ERRORS = 200

    def __init__(self) -> None:
        self.transferred = 0
        self.deleted = 0
        self.error_count = 0
        self._errors: deque[str] = deque(maxlen=self.MAX_ERRORS)

    def feed_record(self, record: dict) -> None:
        level = record.get("level", "")
        msg = record.get("msg", "")
        if level == "error":
            self.error_count += 1
            self._errors.append(msg)
        elif "Copied" in msg or "Moved" in msg or "Deleted" in msg:
            # Per-file records ("clip.mov: Copied (new)") only — the run-
            # summary stats line ("Transferred: 0 B / ...") must not count
            # as a file, which is why "Transferred" is NOT matched here.
            self.transferred += 1
            if "Deleted" in msg:
                self.deleted += 1

    def result(self) -> RcloneRunResult:
        return RcloneRunResult(
            ok=not self.error_count,
            transferred=self.transferred,
            errors=list(self._errors),
            raw_returncode=0,
            error_count=self.error_count,
            deleted=self.deleted,
        )


def parse_json_log(text: str) -> RcloneRunResult:
    """Parse rclone --use-json-log stderr output into a summary.

    Tolerant of non-JSON lines (rclone occasionally emits plain text for
    config-file notices etc.) — those are skipped rather than raising.

    Still the whole-text entry point (the legacy injected-subprocess_run path
    and the express run both hand it a complete, small stderr); the streaming
    periodic runner uses RcloneRunTally, which applies the identical rules
    per line.
    """
    tally = RcloneRunTally()
    for line in text.splitlines():
        line = line.strip()
        if not line or not line.startswith("{"):
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        tally.feed_record(record)
    return tally.result()


def _project_rel_for_path(
    local_root: str, path: str, known_rels: Optional[list[str]] = None
) -> Optional[str]:
    """Given an absolute file path under local_root, return the
    "Projects/<rel>" subtree it belongs to.

    With `known_rels` (posix rels like "2026/CCT/Creator Profiles/Season 1",
    from the sequencer's selection), the LONGEST rel whose segments prefix
    the path wins -- projects live at any depth since 2026-07-25, so fixed
    slicing can't work. `known_rels is None` means NO selection source is
    wired at all (legacy whole-tree mode) and only then is the original
    year/series/project heuristic (first 3 components) used.

    An EMPTY list is not the same thing and must not fall through to that
    heuristic: `if known_rels:` treated [] like None, and the sequencer
    returns [] before its first fetch and whenever the dashboard is
    unreachable -- so a watchdog event during that window was attributed to a
    guessed "Projects/<year>/<series>/<project>" and express-uploaded a file
    from an UNSELECTED project to the NAS, which is precisely the scope
    express is documented never to exceed (AUDIT_3 M-4). Wired but empty
    means "we know of no projects", i.e. nothing is in scope."""
    try:
        rel = Path(path).relative_to(Path(local_root))
    except ValueError:
        return None
    parts = rel.parts
    if len(parts) < 2 or parts[0] != "Projects":
        return None
    inner = [p.lower() for p in parts[1:]]

    if known_rels is not None:
        best: Optional[str] = None
        best_len = 0
        for known in known_rels:
            segs = [s.lower() for s in known.strip("/").split("/") if s]
            if len(segs) < len(inner) and inner[: len(segs)] == segs and len(segs) > best_len:
                best, best_len = known, len(segs)
        return f"Projects/{best}" if best else None

    if len(parts) < 4:
        return None
    return "/".join(parts[:4])


class RcloneLane(LaneAdapter):
    """One rclone-backed lane. direction="up" -> Lane A, direction="down" -> Lane B."""

    def __init__(
        self,
        direction: str,
        local_root: str,
        remote: str,
        remote_root: str,
        rclone_path: str = "rclone",
        transfers: int = 4,
        scan_interval: float = 300.0,
        watch_debounce_seconds: float = 10.0,
        state_dir: Optional[Path] = None,
        subprocess_run=subprocess.run,
        popen_factory=None,
        on_change: Optional[Callable[[str], None]] = None,
        known_rels_fn: Optional[Callable[[], list[str]]] = None,
        cfg: Optional[dict] = None,
        on_trash: Optional[Callable[[str], None]] = None,
    ) -> None:
        assert direction in (DIRECTION_UP, DIRECTION_DOWN)
        self.direction = direction
        self.name = "lane_a_video_up" if direction == DIRECTION_UP else "lane_b_proxy_down"
        self.local_root = local_root
        self.remote = remote
        self.remote_root = remote_root
        self.rclone_path = rclone_path
        self.transfers = transfers
        self.scan_interval = scan_interval
        self.watch_debounce_seconds = watch_debounce_seconds
        self.subprocess_run = subprocess_run
        self.popen_factory = popen_factory
        self.on_change = on_change
        # Called with the run's --backup-dir after a lane B run that actually
        # moved something into it -- see _notify_trash. Same injectable
        # callback shape as on_change.
        self.on_trash = on_trash
        # Selected-project rels (any depth) for the watchdog's project
        # attribution -- see _project_rel_for_path. None = legacy heuristic.
        self.known_rels_fn = known_rels_fn
        # Transport tuning (AUDIT_2 P1/P2/§4.2). `cfg` is optional so a
        # caller that doesn't pass one still gets the recommended defaults
        # rather than rclone's -- the flags are the fix, config is only the
        # override seam (C-5).
        self.tuning = RcloneTuning.from_cfg(cfg)
        # Last orphan-.partial scan (P8/P15/C-7): REPORTED, never deleted.
        self._orphans: Optional[dict] = None

        # Backward-compat seam: a caller that injects a custom subprocess_run
        # (and no popen_factory) keeps the old subprocess.run() code path —
        # this is only true when subprocess_run was actually overridden, not
        # left at its subprocess.run default, which always uses the newer
        # Popen-based runner (needed for live --stats parsing).
        self._legacy_run = popen_factory is None and subprocess_run is not subprocess.run

        self._state_dir = state_dir or (Path.home() / ".ccsync" / "state")
        self._filter_file = self._state_dir / f"filter_{direction}.txt"

        # ONE EVENT PER THREAD GENERATION. A single long-lived event that
        # start() cleared and stop() set could only ever be right for one of
        # the two: clearing re-armed a stale thread (thread leak), and not
        # clearing left the lane permanently dead once stop()'s 5 s join
        # timed out mid-rclone-run -- which it routinely does (AUDIT_2 L-2,
        # a regression from round 1's leak fix). With a fresh Event per
        # generation, the stale thread keeps its own SET event and exits on
        # its own, and a new generation can always start.
        self._stop_event = threading.Event()
        self._periodic_thread: Optional[threading.Thread] = None
        # Live rclone child, so stop() can actually end a transfer instead
        # of orphaning it (AUDIT_2 L-12/C-7: an orphaned lane B `sync`
        # racing the newly-spawned companion's own lane B is two concurrent
        # syncs of the same destination).
        self._proc = None
        self._observer = None  # watchdog Observer, lane A only
        self._debounce_timer: Optional[threading.Timer] = None
        self._lock = threading.Lock()
        # Serializes rclone runs: the periodic loop and a debounced watchdog
        # fire must never run two rclone processes on the same lane at once.
        self._run_lock = threading.Lock()
        self._status = LaneStatus(name=self.name)

        # -- express lane A (AUDIT_2 C-2 / P9) -------------------------
        # Config is read here rather than in config.py's defaults because
        # this module doesn't own config.py; every key is a cfg.get() with
        # the default beside it.
        self._express_enabled = (
            direction == DIRECTION_UP
            and bool((cfg or {}).get("express_upload_enabled", EXPRESS_DEFAULT_ENABLED))
        )
        # P9's fix for the dead knob: watch_debounce_seconds was unreachable
        # in managed mode (on_change short-circuits _schedule_debounced_run),
        # and it is the natural control for the express window, so it now
        # drives it. express_debounce_seconds overrides it if an operator
        # wants the two decoupled.
        debounce = (cfg or {}).get("express_debounce_seconds", watch_debounce_seconds)
        try:
            self._express_debounce = max(0.1, float(debounce))
        except (TypeError, ValueError):
            log.warning(
                "express: express_debounce_seconds=%r is not a number -- using %ss",
                debounce, watch_debounce_seconds,
            )
            self._express_debounce = max(0.1, float(watch_debounce_seconds))
        self._express_max_batch = _cfg_int(cfg, "express_max_batch", EXPRESS_DEFAULT_MAX_BATCH)
        # ITS OWN LOCK, emphatically not _run_lock: reusing that would queue
        # the express run behind an in-flight 40 GB periodic upload, which is
        # exactly the latency the feature exists to remove (AUDIT_2 C-2).
        # Two concurrent rclones on the same tree are safe here *because*
        # both are upload-only `copy --ignore-existing`.
        self._express_run_lock = threading.Lock()
        self._express_lock = threading.Lock()  # guards the pending map/timer
        # rel(posix) -> (last observed size, first seen monotonic)
        self._express_pending: dict[str, tuple[int, float]] = {}
        self._express_timer: Optional[threading.Timer] = None
        self._express_proc = None
        self._express_shutdown = threading.Event()
        # "Pause syncing" (tray) -- distinct from _express_shutdown, which is
        # latched off by stop() for a whole thread generation. See
        # pause_express().
        self._express_paused = threading.Event()
        self._express_seq = 0
        # Lane B's --backup-dir for the run in flight (see _notify_trash).
        self._last_backup_dir: Optional[str] = None
        self._express_status: dict = {
            "enabled": self._express_enabled,
            "runs": 0,
            "files_uploaded": 0,
            "dropped_over_cap": 0,
            "last_run": None,
            "last_files": 0,
            "last_error": None,
        }

    # -- filter file -------------------------------------------------
    def _ensure_filter_file(self) -> Path:
        rules = build_filter_rules_up() if self.direction == DIRECTION_UP else build_filter_rules_down()
        return write_filter_file(rules, self._filter_file)

    def _backup_dir(self, subpath: Optional[str] = None) -> str:
        """Where lane B's deletions go instead of away.

        One directory per run (timestamped) and keyed by project subpath, so
        a recovery is unambiguous: `<local_root>/.ccsync-trash/<ts>/Projects/
        <rel>/<the file's original relative path>`. Nothing ever prunes it --
        deleting the recovery copy would defeat its whole purpose, and the
        hard requirement outranks the disk-hygiene gain (AUDIT_2 C-7)."""
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        base = Path(self.local_root) / TRASH_DIR_NAME / stamp
        local_sub = _local_subpath(subpath)
        return str(base / local_sub) if local_sub else str(base)

    def _build_command(
        self,
        subpath: Optional[str] = None,
        stats_interval: Optional[str] = None,
        max_duration_seconds: Optional[float] = None,
    ) -> list[str]:
        filter_file = self._ensure_filter_file()
        if self.direction == DIRECTION_UP:
            return build_up_command(
                self.rclone_path, self.local_root, self.remote, self.remote_root,
                filter_file, self.transfers, subpath=subpath, stats_interval=stats_interval,
                max_duration_seconds=max_duration_seconds, tuning=self.tuning,
            )
        # Remembered so the run can tell the editor WHERE its files went --
        # see _notify_trash. Safe as instance state: run_once holds _run_lock,
        # and only lane A has the (separately locked) express path.
        backup_dir = self._backup_dir(subpath)
        self._last_backup_dir = backup_dir
        return build_down_command(
            self.rclone_path, self.local_root, self.remote, self.remote_root,
            filter_file, self.transfers, subpath=subpath, stats_interval=stats_interval,
            backup_dir=backup_dir, max_duration_seconds=max_duration_seconds,
            tuning=self.tuning,
        )

    # -- LaneAdapter ---------------------------------------------------
    def start(self) -> None:
        if (
            self._periodic_thread is not None
            and self._periodic_thread.is_alive()
            and not self._stop_event.is_set()
        ):
            # Genuinely already running under a live generation -> idempotent
            # per LaneAdapter's contract, nothing to do.
            return

        available, msg = rclone_available(self.rclone_path)
        if not available:
            with self._lock:
                self._status.state = STATE_ERROR
                self._status.last_error = msg
            log.error("%s: %s", self.name, msg)
            return

        if self._periodic_thread is not None and self._periodic_thread.is_alive():
            # stop()'s 5 s join timed out mid-rclone-run and the old thread
            # is still winding down. Its event is already set and belongs to
            # IT alone, so it will exit after its current run and can never
            # be re-armed -- we can safely start a fresh generation now
            # instead of leaving the lane dead forever (AUDIT_2 L-2).
            log.info(
                "%s: previous periodic thread still winding down; starting a "
                "fresh generation alongside it", self.name,
            )
        # Retire whatever generation came before (a no-op when stop() already
        # set it) and hand the new thread its own event.
        self._stop_event.set()
        stop_event = threading.Event()
        self._stop_event = stop_event
        self._periodic_thread = threading.Thread(
            target=self._periodic_loop, args=(stop_event,),
            name=f"ccsync-{self.name}-periodic", daemon=True,
        )
        self._periodic_thread.start()

        if self.direction == DIRECTION_UP:
            self._start_watchdog()

    def start_watchdog_only(self) -> None:
        """Start just the filesystem watcher, no periodic loop. Managed mode
        (sequencer-driven) uses this so file events still reach on_change
        while run_once() stays externally driven."""
        if self.direction != DIRECTION_UP or self._observer is not None:
            return
        # AUDIT_2 P9's second half: this entry point IS managed mode, and no
        # periodic loop is ever started here, so scan_interval_up /
        # scan_interval_down do nothing at all. Say so once, out loud,
        # instead of leaving two knobs that silently no-op. (The third dead
        # knob, watch_debounce_seconds, is no longer dead -- it now drives
        # the express window below.)
        log.warning(
            "%s: managed mode -- scan_interval_up/scan_interval_down are IGNORED "
            "(the sequencer drives every pass; scan_interval=%ss unused). "
            "watch_debounce_seconds=%.1fs now sets the express-upload window.",
            self.name, self.scan_interval, self._express_debounce,
        )
        if self._periodic_thread is None or not self._periodic_thread.is_alive():
            # No live periodic generation to signal, so a fresh (cleared)
            # event is the right target for the next stop(). Never clear the
            # existing one in place -- that is exactly what re-armed a stale
            # thread before generation events existed.
            self._stop_event = threading.Event()
        self._start_watchdog()

    def stop(self) -> None:
        self._stop_event.set()
        self._express_stop()
        if self._periodic_thread is not None:
            # Bounded join: an in-flight rclone run can take minutes, and
            # stop() must never block that long. Timing out is fine now --
            # the thread owns its own (set) event, so it exits on its own and
            # start() can begin a fresh generation immediately.
            self._periodic_thread.join(timeout=5)
        # Kill the child rather than orphan it: on Windows the rclone process
        # outlives the parent, so a self-upgrade would otherwise leave the
        # old lane B `sync` racing the new process's lane B over the same
        # destination (AUDIT_2 L-12/C-7).
        self._kill_running_process()
        if self._debounce_timer is not None:
            self._debounce_timer.cancel()
        if self._observer is not None:
            try:
                self._observer.stop()
                self._observer.join(timeout=5)
            except Exception:
                pass
            self._observer = None

    def _express_stop(self) -> None:
        """Disarm the express path and end an in-flight express rclone.

        Same reasoning as _kill_running_process: on Windows the child
        outlives the parent, so a self-upgrade would otherwise leave an
        express upload running alongside the new process's lanes (AUDIT_2
        C-7). Harmless for correctness -- express only ever copies -- but
        two of them wasting the same uplink is not."""
        self._express_shutdown.set()
        with self._express_lock:
            timer, self._express_timer = self._express_timer, None
            self._express_pending = {}
        if timer is not None:
            timer.cancel()
        proc = self._express_proc
        if proc is None:
            return
        try:
            if proc.poll() is not None:
                return
            log.info("%s: terminating in-flight express rclone on stop()", self.name)
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except Exception:
                proc.kill()
        except Exception:
            log.debug("%s: could not terminate express rclone child", self.name, exc_info=True)

    def _kill_running_process(self) -> None:
        proc = self._proc
        if proc is None:
            return
        try:
            if proc.poll() is not None:
                return
            log.info("%s: terminating in-flight rclone on stop()", self.name)
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except Exception:
                proc.kill()
        except Exception:
            log.debug("%s: could not terminate rclone child", self.name, exc_info=True)

    def status(self) -> LaneStatus:
        with self._lock:
            return LaneStatus(**vars(self._status))

    # -- leftovers: reported, never deleted (AUDIT_2 P8/P15/C-7) ----------
    def refresh_orphan_report(self, subpath: Optional[str] = None) -> Optional[dict]:
        """One NAS listing for `*.partial` plus a local `.ccsync-trash` walk.

        Costs an SFTP listing, so the sequencer runs it every N passes rather
        than every pass. Result is cached for orphan_report(); nothing here
        removes a single byte."""
        if self.direction != DIRECTION_UP:
            return None
        partials = scan_orphan_partials(
            self.rclone_path, self.remote, self.remote_root, subpath
        )
        trash = scan_trash_dir(self.local_root)
        report = {
            "subpath": subpath,
            "partials": partials,
            "trash": trash,
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }
        if partials and partials.get("count"):
            log.warning(
                "%s: %d orphan .partial file(s) (%.1f GB) under %s on the NAS -- "
                "left in place deliberately (never deleted); remove them by hand "
                "if you want the space back",
                self.name, partials["count"], partials["bytes"] / 1e9, subpath or "the remote root",
            )
        with self._lock:
            self._orphans = report
        return report

    def orphan_report(self) -> Optional[dict]:
        """Last refresh_orphan_report() result, or None if never run.

        Public so the reporter payload (owned elsewhere) and the tray can
        surface it without re-listing the NAS."""
        with self._lock:
            return dict(self._orphans) if self._orphans else None

    def run_once(
        self, subpath: Optional[str] = None, max_duration_seconds: Optional[float] = None
    ) -> LaneStatus:
        """One synchronous pass. `max_duration_seconds` is a per-project time
        budget (the sequencer passes project_rotation_seconds) -- without it
        a single 200 GB ingest holds _run_lock, and therefore every other
        project's lanes, for as long as it takes (AUDIT_2 L-4)."""
        with self._run_lock:
            return self._run_once_locked(subpath, max_duration_seconds)

    def _run_once_locked(
        self, subpath: Optional[str] = None, max_duration_seconds: Optional[float] = None
    ) -> LaneStatus:
        available, msg = rclone_available(self.rclone_path)
        if not available:
            with self._lock:
                self._status.state = STATE_ERROR
                self._status.last_error = msg
            return self.status()

        if self.direction == DIRECTION_UP and subpath:
            # Lane A pushes local -> NAS; if the project folder hasn't been
            # created locally yet (e.g. not accepted/mapped yet), there is
            # nothing to run — and rclone would just error on a missing
            # source dir, which we don't want treated as a real failure.
            project_dir = Path(self.local_root) / subpath
            if not project_dir.exists():
                with self._lock:
                    self._status.state = STATE_IDLE
                    self._status.detail = f"project dir not yet local: {subpath}"
                return self.status()

        with self._lock:
            self._status.state = STATE_SYNCING
            self._status.transferring = 1
            self._status.current_project = subpath
            self._status.bytes_done = None
            self._status.bytes_total = None
            self._status.speed_bps = None
            self._status.eta_seconds = None
            self._status.transfers = []

        stats_interval = None if self._legacy_run else "10s"
        try:
            cmd = self._build_command(
                subpath=subpath,
                stats_interval=stats_interval,
                max_duration_seconds=max_duration_seconds,
            )
        except FilterFileError as exc:
            # Fail the run, loudly, rather than let rclone run unfiltered:
            # for lane B that is `sync` with no filter, which deletes every
            # local file the NAS lacks (AUDIT_2 DEL-2).
            log.error("%s: refusing to run -- %s", self.name, exc)
            with self._lock:
                self._status.state = STATE_ERROR
                self._status.last_error = str(exc)
                self._status.transferring = 0
                self._status.current_project = None
            return self.status()

        if self._legacy_run:
            try:
                proc = self.subprocess_run(
                    cmd,
                    capture_output=True,
                    timeout=None,
                    encoding="utf-8",
                    errors="replace",
                    creationflags=_win_creationflags(),
                )
            except Exception as exc:
                with self._lock:
                    self._status.state = STATE_ERROR
                    self._status.last_error = str(exc)
                    self._status.transferring = 0
                    self._status.current_project = None
                return self.status()
            returncode = proc.returncode
            stderr_text = proc.stderr or ""
            result = parse_json_log(stderr_text)
        else:
            try:
                returncode, stderr_text, result = self._run_popen(cmd)
            except Exception as exc:
                with self._lock:
                    self._status.state = STATE_ERROR
                    self._status.last_error = str(exc)
                    self._status.transferring = 0
                    self._status.speed_bps = None
                    self._status.eta_seconds = None
                    self._status.transfers = []
                    self._status.current_project = None
                return self.status()

        with self._lock:
            self._status.transferring = 0
            self._status.queued = 0
            # No longer transferring — bytes_done/bytes_total keep their
            # final values, but speed/eta/per-file transfers stop making
            # sense once idle. current_project must clear too, or the
            # dashboard keeps the last-synced project wearing
            # "[ SYNCING NOW ]" for as long as the process lives
            # (AUDIT_2 UX-14).
            self._status.speed_bps = None
            self._status.eta_seconds = None
            self._status.transfers = []
            self._status.current_project = None
            # Exit code is authoritative: rclone logs transient per-attempt
            # failures at error level ("Attempt 1/3 failed ...") even when a
            # retry succeeds and the run as a whole is fine.
            if returncode == RCLONE_EXIT_MAX_DURATION and max_duration_seconds:
                # The per-project budget ran out. With --cutoff-mode SOFT
                # everything already in flight completed; the rest is picked
                # up next pass. A bounded stop, not a failure -- painting the
                # lane red here would make normal rotation look broken.
                log.info(
                    "%s: hit the %ss per-project budget for %s -- remaining files "
                    "resume next pass", self.name, int(max_duration_seconds), subpath,
                )
                self._status.state = STATE_IDLE
                self._status.last_error = None
                self._status.last_sync = datetime.now(timezone.utc)
                self._status.detail = (
                    f"transferred {result.transferred} file(s), paused at the "
                    f"{int(max_duration_seconds)}s project budget"
                )
            elif returncode != 0:
                self._status.state = STATE_ERROR
                tail = result.errors[-1] if result.errors else stderr_text.strip()[-300:]
                self._status.last_error = tail or f"rclone exited {returncode}"
            else:
                if result.errors:
                    log.info("%s: %d transient error line(s), run succeeded (last: %s)",
                             self.name, result.error_count or len(result.errors),
                             result.errors[-1])
                self._status.state = STATE_IDLE
                self._status.last_error = None
                self._status.last_sync = datetime.now(timezone.utc)
                self._status.detail = f"transferred {result.transferred} file(s)"
        self._notify_trash(result)
        return self.status()

    def _notify_trash(self, result: RcloneRunResult) -> None:
        """Tell the editor when lane B moved local files into .ccsync-trash.

        Lane B is `sync` with --backup-dir, so anything the NAS doesn't have
        under **/Proxy/** -- INCLUDING proxies the editor generated locally
        and hasn't uploaded -- is moved out of the project directory. Nothing
        said so: the files simply vanished from the folder the editor was
        working in, and the recovery copy under <local_root>/.ccsync-trash/
        <timestamp>/ is undiscoverable unless you know it exists (AUDIT_3
        L-12). Deletion behaviour is unchanged; this only surfaces it.

        Never raises -- a failed stat or a callback that throws must not fail
        the lane run."""
        if self.direction != DIRECTION_DOWN or self.on_trash is None:
            return
        backup_dir = self._last_backup_dir
        self._last_backup_dir = None
        if not backup_dir:
            return
        try:
            # The directory is created by rclone only when it actually moves
            # something into it -- its existence IS the signal.
            if not Path(backup_dir).is_dir():
                return
            if not any(Path(backup_dir).rglob("*")):
                return
        except OSError:
            log.debug("%s: could not inspect the backup dir %s", self.name, backup_dir)
            return
        log.warning(
            "%s: %d local file(s) not present on the NAS were moved to %s -- "
            "nothing was deleted, recover them from there",
            self.name, result.deleted, backup_dir,
        )
        try:
            self.on_trash(str(backup_dir))
        except Exception:
            log.exception("%s: on_trash callback failed", self.name)

    # -- Popen-based runner with live --stats JSON parsing ---------------
    def _run_popen(self, cmd: list[str]) -> tuple[int, str, RcloneRunResult]:
        """Run rclone, parsing its stderr AS IT ARRIVES.

        Returns (returncode, bounded stderr tail, incremental parse result).
        The tail is STDERR_TAIL_LINES lines, not the whole stream: see
        RcloneRunTally for why keeping all of it was a memory problem on real
        ingests (AUDIT_3 M-8)."""
        factory = self.popen_factory or subprocess.Popen
        proc = factory(
            cmd,
            stderr=subprocess.PIPE,
            encoding="utf-8",
            errors="replace",
            creationflags=_win_creationflags(),
        )
        tail: deque[str] = deque(maxlen=STDERR_TAIL_LINES)
        tally = RcloneRunTally()

        def _reader() -> None:
            # Never let a decode/IO error escape this thread: with no
            # try/except here, one non-ASCII filename raising inside the
            # loop would kill the reader silently, nobody would drain
            # proc.stderr, rclone would block on a full pipe once its 64 KB
            # buffer fills, and proc.wait() below would never return --
            # deadlocking _run_lock (and the whole sequencer) forever.
            try:
                for line in proc.stderr:
                    tail.append(line)
                    self._handle_stderr_line(line, tally)
            except Exception:
                log.exception(
                    "%s: stderr reader failed -- killing rclone so proc.wait() "
                    "cannot deadlock", self.name,
                )
                try:
                    proc.kill()
                except Exception:
                    pass

        reader_thread = threading.Thread(
            target=_reader, name=f"ccsync-{self.name}-stderr-reader", daemon=True
        )
        reader_thread.start()
        # Published so stop() can end this child instead of orphaning it.
        self._proc = proc
        try:
            returncode = proc.wait()
        finally:
            self._proc = None
        reader_thread.join()
        return returncode, "".join(tail), tally.result()

    def _handle_stderr_line(self, line: str, tally: Optional[RcloneRunTally] = None) -> None:
        """Live --stats parse for ONE stderr line, plus the run tally.

        `tally` is optional so the line handler stays callable on its own
        (tests, and any future caller that only wants the status side)."""
        line = line.strip()
        if not line or not line.startswith("{"):
            return
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            return
        if tally is not None:
            # Counted HERE rather than by re-parsing the whole stream at the
            # end of the run -- that required keeping the whole stream
            # (AUDIT_3 M-8).
            tally.feed_record(record)
        stats = record.get("stats")
        if not isinstance(stats, dict):
            return
        with self._lock:
            self._status.bytes_done = stats.get("bytes")
            self._status.bytes_total = stats.get("totalBytes")
            self._status.speed_bps = stats.get("speed")
            self._status.eta_seconds = stats.get("eta")
            self._status.transfers = self._normalize_transferring(stats.get("transferring"))

    def _normalize_transferring(self, transferring: Optional[list]) -> list[dict]:
        """Normalize rclone --stats JSON's "transferring" array (per-file, live
        mid-transfer only -- absent/empty between files or once idle) into the
        dashboard's "transfers" shape. Direction is fixed per-lane."""
        direction = DIRECTION_UP if self.direction == DIRECTION_UP else DIRECTION_DOWN
        if not transferring:
            return []
        result: list[dict] = []
        for entry in transferring:
            if not isinstance(entry, dict):
                continue
            result.append(
                {
                    "name": entry.get("name"),
                    "direction": direction,
                    "bytes_done": entry.get("bytes"),
                    "bytes_total": entry.get("size"),
                    "percentage": entry.get("percentage"),
                    "speed_bps": entry.get("speed"),
                    "eta_seconds": entry.get("eta"),
                }
            )
        return result

    # -- periodic pass ---------------------------------------------------
    def _periodic_loop(self, stop_event: Optional[threading.Event] = None) -> None:
        # This generation's own event is passed in by start(); a thread must
        # never read self._stop_event, which by then may belong to a NEWER
        # generation (AUDIT_2 L-2).
        stop_event = stop_event if stop_event is not None else self._stop_event
        # Run once immediately on start, then every scan_interval.
        while not stop_event.is_set():
            try:
                self.run_once()
            except Exception:
                log.exception("%s: periodic pass failed", self.name)
            if stop_event.wait(self.scan_interval):
                break

    # -- watchdog (lane A only) -------------------------------------------
    def _start_watchdog(self) -> None:
        # Re-arm express for this generation (stop() latched it off).
        self._express_shutdown.clear()
        self._sweep_stale_express_lists()
        try:
            from watchdog.events import FileSystemEventHandler
            from watchdog.observers import Observer
        except ImportError:
            log.warning(
                "%s: 'watchdog' not installed -- falling back to periodic-only "
                "uploads every %ss", self.name, self.scan_interval,
            )
            return

        lane = self

        class _Handler(FileSystemEventHandler):
            def on_created(self, event):
                self._maybe_trigger(event)

            def on_modified(self, event):
                self._maybe_trigger(event)

            def on_moved(self, event):
                self._maybe_trigger(event)

            def _maybe_trigger(self, event) -> None:
                if event.is_directory:
                    return
                path = getattr(event, "dest_path", None) or event.src_path
                if not path_matches_lane_a_filter(path):
                    return
                if lane.on_change is not None:
                    # Per-project mode: hand off to the (separately built)
                    # sequencer instead of running a debounced whole-tree
                    # pass. Known project rels (any depth) come from the
                    # sequencer's selection via known_rels_fn; a file not
                    # under any known project is ignored rather than falling
                    # back to the old whole-tree trigger.
                    knowns = None
                    if lane.known_rels_fn is not None:
                        try:
                            knowns = list(lane.known_rels_fn())
                        except Exception:
                            # NOT None: None means "no selection source is
                            # wired", which turns the legacy first-3-
                            # components heuristic back on and would push a
                            # file from an unselected project (AUDIT_3 M-4).
                            # A selection source that can't answer means
                            # nothing is known to be in scope.
                            knowns = []
                    rel = _project_rel_for_path(lane.local_root, path, knowns)
                    if rel is not None:
                        # Express upload (AUDIT_2 C-2): the exact path, in its
                        # own short-lived rclone seconds after it settles,
                        # instead of whenever rotation reaches this project.
                        # Purely additive -- the sequencer's full pass is
                        # still the safety net. Deliberately INSIDE the
                        # rel-is-known branch: express must cover exactly the
                        # scope the periodic lane A covers, never more. A file
                        # under an unselected (or pre-repath, stale-named)
                        # project must not be pushed to the NAS out of turn.
                        lane.notify_path_changed(path)
                        lane.on_change(rel)
                    return
                # Legacy whole-tree mode: the debounced pass below covers the
                # whole local_root, so express is in scope for any match.
                lane.notify_path_changed(path)
                lane._schedule_debounced_run()

        try:
            observer = Observer()
            observer.schedule(_Handler(), self.local_root, recursive=True)
            observer.start()
            self._observer = observer
        except Exception as exc:
            log.warning("%s: failed to start watchdog observer: %s", self.name, exc)

    def _schedule_debounced_run(self) -> None:
        with self._lock:
            if self._debounce_timer is not None:
                self._debounce_timer.cancel()
            self._debounce_timer = threading.Timer(self.watch_debounce_seconds, self._debounced_fire)
            self._debounce_timer.daemon = True
            self._debounce_timer.start()

    def _debounced_fire(self) -> None:
        try:
            self.run_once()
        except Exception:
            log.exception("%s: debounced run failed", self.name)

    # -- express lane A (AUDIT_2 C-2 / P9) --------------------------------
    #
    # Today an editor drops a clip in and nothing moves until the sequencer's
    # rotation reaches that project (minutes at best, a whole pass at worst).
    # The watchdog already knows the exact path, so a second, short-lived
    # rclone uploads just that path: 1 stat + 1 upload instead of a full-tree
    # traverse.
    #
    # SAFETY, since this is the one place the system runs two rclones at once:
    # the express argv is `copy --ignore-existing` with an explicit file list.
    # It has no delete verb, cannot overwrite an existing remote file, and
    # never touches .partial files. The periodic pass is unchanged and still
    # runs -- express is an addition, never a replacement.

    def _sweep_stale_express_lists(self) -> None:
        """Drop express list files a hard kill left behind.

        Scoped as narrowly as it can be: only `express_*.txt` in OUR state
        dir, only when older than a day (so a list another live companion's
        rclone is reading is never touched), and failures are ignored. These
        are the lane's own scratch artifacts -- the never-delete rule is
        about user data, and nothing here can reach any."""
        try:
            cutoff = time.time() - EXPRESS_LIST_STALE_SECONDS
            for path in Path(self._state_dir).glob("express_*.txt"):
                try:
                    if path.stat().st_mtime < cutoff:
                        path.unlink()
                except OSError:
                    pass
        except OSError:
            pass

    def express_report(self) -> dict:
        """Counters for the reporter/tray (owned elsewhere). Read-only."""
        with self._lock:
            return dict(self._express_status)

    def pause_express(self) -> None:
        """Stop the express lane until resume_express().

        THE TRAY'S "Pause syncing" DID NOT STOP UPLOADS in managed mode: it
        only called sequencer.pause(), which halts the rotation -- while lane
        A's watchdog kept calling notify_path_changed() and express kept
        spawning its own rclone, so a "paused" editor went on pushing every
        new clip to the NAS (AUDIT_3 M-3). app.toggle_pause() calls this
        explicitly rather than reaching into the privates.

        Drops whatever is pending and cancels the armed timer -- the periodic
        pass (which pause really does stop) is the safety net, so nothing is
        lost, it is merely deferred. Never raises."""
        self._express_paused.set()
        with self._express_lock:
            timer, self._express_timer = self._express_timer, None
            self._express_pending = {}
        if timer is not None:
            try:
                timer.cancel()
            except Exception:
                log.debug("%s: express timer cancel failed", self.name, exc_info=True)
        log.info("%s: express uploads paused", self.name)

    def resume_express(self) -> None:
        """Re-arm the express lane after pause_express(). Never raises."""
        self._express_paused.clear()
        log.info("%s: express uploads resumed", self.name)

    def express_paused(self) -> bool:
        return self._express_paused.is_set()

    def notify_path_changed(self, path: str) -> None:
        """Queue one changed absolute path for the express upload.

        Public because the watchdog handler is not the only plausible caller
        (a future Resolve-side hint would use the same door). Never raises:
        a bad path is dropped and the periodic pass still covers the file.
        """
        if (
            not self._express_enabled
            or self._express_shutdown.is_set()
            or self._express_paused.is_set()
        ):
            return
        try:
            rel = self._express_rel(path)
        except Exception:
            log.debug("%s: express could not relativize %r", self.name, path, exc_info=True)
            return
        if rel is None or not path_matches_lane_a_filter(rel):
            return
        try:
            size = os.path.getsize(path)
        except OSError:
            # Gone already (temp file, cancelled copy) -- nothing to upload.
            return

        now = time.monotonic()
        with self._express_lock:
            existing = self._express_pending.get(rel)
            if existing is None and len(self._express_pending) >= self._express_max_batch:
                # Over the cap: drop it and let the periodic full pass do the
                # work. Logged at most once per batch, because the watchdog
                # fires thousands of times a minute during a card ingest.
                if self._express_status.get("dropped_over_cap", 0) % 1000 == 0:
                    log.info(
                        "%s: express batch is at its %d-path cap -- extra paths "
                        "are left to the periodic pass",
                        self.name, self._express_max_batch,
                    )
                with self._lock:
                    self._express_status["dropped_over_cap"] += 1
                return
            first_seen = existing[1] if existing else now
            # Re-recording the size on every event is the coalescing AND the
            # stability check in one: a file still being written has a
            # different size by the time the window closes.
            self._express_pending[rel] = (size, first_seen)
            self._express_arm_timer_locked()

    def _express_rel(self, path: str) -> Optional[str]:
        """Absolute path -> posix rel under local_root, or None if outside.

        os.path.normcase, not Path.relative_to: an editor's watchdog reports
        `P:\\Projects\\...` while local_root may be `p:\\projects`, and a
        case-sensitive comparison would silently disable express on exactly
        the machines it is for."""
        root = os.path.normcase(os.path.normpath(str(self.local_root)))
        full = os.path.normcase(os.path.normpath(str(path)))
        if not full.startswith(root.rstrip("\\/") + os.sep) and full != root:
            return None
        rel = os.path.relpath(os.path.normpath(str(path)), os.path.normpath(str(self.local_root)))
        rel = rel.replace("\\", "/")
        if rel.startswith("../") or rel == "..":
            return None
        return rel

    def _express_arm_timer_locked(self, delay: Optional[float] = None) -> None:
        """Schedule the flush. Caller holds _express_lock.

        Deliberately a FIXED window anchored on the first event, not a timer
        restarted per event: the watchdog fires per write chunk, so a
        restart-on-every-event debounce would never fire at all during a
        long ingest. This way each window closes on time and everything
        seen inside it is coalesced into one list file, one rclone."""
        if self._express_timer is not None or self._express_shutdown.is_set():
            return
        timer = threading.Timer(
            self._express_debounce if delay is None else delay, self._express_flush
        )
        timer.daemon = True
        self._express_timer = timer
        timer.start()

    def _express_flush(self) -> None:
        try:
            self._express_flush_inner()
        except Exception:
            log.exception("%s: express flush failed", self.name)

    def _express_flush_inner(self) -> None:
        with self._express_lock:
            self._express_timer = None
            batch = self._express_pending
            self._express_pending = {}
        if self._express_shutdown.is_set() or self._express_paused.is_set():
            # A timer armed a moment before pause_express() must not fire an
            # upload after it (AUDIT_3 M-3).
            return

        ready, deferred = self._express_partition(batch)

        if deferred:
            with self._express_lock:
                for rel, entry in deferred.items():
                    if rel in self._express_pending:
                        continue
                    if len(self._express_pending) >= self._express_max_batch:
                        break
                    self._express_pending[rel] = entry
                self._express_arm_timer_locked()

        if not ready:
            return

        # Non-blocking: if an express run is already uploading, keep the
        # batch and try again next window rather than piling up rclones.
        if not self._express_run_lock.acquire(blocking=False):
            with self._express_lock:
                for rel in ready:
                    self._express_pending.setdefault(rel, (-1, time.monotonic()))
                self._express_arm_timer_locked()
            return
        try:
            self._express_run(ready)
        finally:
            self._express_run_lock.release()

    def _express_partition(
        self, batch: dict[str, tuple[int, float]]
    ) -> tuple[list[str], dict[str, tuple[int, float]]]:
        """Split a coalesced batch into (uploadable now, look again later).

        This is where --min-age lives for the express path: rclone refuses
        --min-age alongside --files-from-raw (measured, see
        build_express_command), so the age gate is applied here -- plus the
        size-stability check L-14 asks for, which --min-age cannot give on an
        mtime-preserving ingest."""
        ready: list[str] = []
        deferred: dict[str, tuple[int, float]] = {}
        now = time.monotonic()
        wall = time.time()
        for rel, (seen_size, first_seen) in batch.items():
            full = os.path.join(str(self.local_root), rel.replace("/", os.sep))
            try:
                st = os.stat(full)
            except OSError:
                continue  # deleted/moved since the event: nothing to upload
            if now - first_seen > EXPRESS_PENDING_MAX_SECONDS:
                log.debug(
                    "%s: express gave up on %s after %.0fs -- the periodic pass owns it",
                    self.name, rel, now - first_seen,
                )
                continue
            if st.st_size != seen_size:
                # Still growing (or shrinking): observe again next window.
                deferred[rel] = (st.st_size, first_seen)
                continue
            if (wall - st.st_mtime) < LANE_A_MIN_AGE_SECONDS:
                # Same gate the periodic pass gets from --min-age.
                deferred[rel] = (st.st_size, first_seen)
                continue
            ready.append(rel)
        return ready, deferred

    def _express_run(self, rels: list[str]) -> None:
        if not self.remote or not self.remote_root:
            # Unconfigured remote: `rclone copy src ":"` is not a shape we
            # want to hand a real binary. Same posture as the lsf helpers.
            log.debug("%s: express upload skipped -- no remote configured", self.name)
            return
        available, msg = rclone_available(self.rclone_path)
        if not available:
            log.warning("%s: express upload skipped -- %s", self.name, msg)
            return

        self._express_seq += 1
        list_file = self._state_dir / (
            f"express_{os.getpid()}_{self._express_seq}_{uuid.uuid4().hex[:8]}.txt"
        )
        try:
            write_files_from_list(rels, list_file)
        except (ExpressListError, OSError) as exc:
            log.warning("%s: express list not written (%s) -- periodic pass will cover it",
                        self.name, exc)
            return

        cmd = build_express_command(
            self.rclone_path, self.local_root, self.remote, self.remote_root,
            list_file, transfers=self.transfers, tuning=self.tuning,
        )
        log.info("%s: express upload of %d path(s)", self.name, len(rels))
        try:
            returncode, stderr_text = self._express_spawn(cmd)
        except Exception as exc:
            log.warning("%s: express upload failed to run: %s", self.name, exc)
            self._express_record(0, str(exc))
            return
        finally:
            # Our own scratch artifact, in our own state dir -- the only
            # thing this feature ever removes. Never user data.
            try:
                os.unlink(list_file)
            except OSError:
                pass

        result = parse_json_log(stderr_text)
        if returncode != 0:
            tail = result.errors[-1] if result.errors else stderr_text.strip()[-300:]
            # Deliberately NOT STATE_ERROR: express is a bonus path and the
            # periodic pass is still the authority on this lane's health.
            # Painting the lane red from here would make a transient express
            # failure look like a broken lane A.
            log.warning("%s: express upload exited %d: %s", self.name, returncode, tail)
            self._express_record(result.transferred, tail or f"rclone exited {returncode}")
            return
        log.info("%s: express uploaded %d file(s)", self.name, result.transferred)
        self._express_record(result.transferred, None)

    def _express_record(self, transferred: int, error: Optional[str]) -> None:
        with self._lock:
            self._express_status["runs"] += 1
            self._express_status["files_uploaded"] += transferred
            self._express_status["last_files"] = transferred
            self._express_status["last_error"] = error
            self._express_status["last_run"] = datetime.now(timezone.utc).isoformat()

    def _express_spawn(self, cmd: list[str]) -> tuple[int, str]:
        """Run the express argv. Mirrors run_once()'s two code paths (the
        injected-subprocess_run seam for tests, Popen otherwise) but keeps
        its OWN child handle: stop() must be able to end an express upload
        without touching the periodic run's, and vice versa."""
        if self._legacy_run:
            proc = self.subprocess_run(
                cmd,
                capture_output=True,
                timeout=None,
                encoding="utf-8",
                errors="replace",
                creationflags=_win_creationflags(),
            )
            return proc.returncode, (proc.stderr or "")

        factory = self.popen_factory or subprocess.Popen
        proc = factory(
            cmd,
            stderr=subprocess.PIPE,
            encoding="utf-8",
            errors="replace",
            creationflags=_win_creationflags(),
        )
        self._express_proc = proc
        try:
            # Single pipe: read to EOF, then wait. No second stream to
            # deadlock against.
            try:
                stderr_text = proc.stderr.read() if proc.stderr is not None else ""
            except Exception:
                log.exception("%s: express stderr read failed -- killing rclone", self.name)
                try:
                    proc.kill()
                except Exception:
                    pass
                stderr_text = ""
            returncode = proc.wait()
        finally:
            self._express_proc = None
        return returncode, stderr_text
