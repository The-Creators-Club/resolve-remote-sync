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
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

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
# At most one files-moved-to-trash TOAST per lane per this many seconds --
# --max-delete-size spreads one large cleanup across many runs, and each run
# used to toast (see _notify_trash). Warnings still log every run.
TRASH_NOTIFY_COOLDOWN_SECONDS = 1800.0
TRASH_EXCLUDE_RULE = f"- /{TRASH_DIR_NAME}/**"

# In-progress sidecars that live INSIDE a Proxy/ dir and must never be pulled
# down. Lane B's include is `**/Proxy/**`, which is every byte under the
# directory -- so while DaVinci Resolve generates a proxy on the base rig it
# writes `.<name>.tmp` (the growing output) plus a 0-byte `.<name>.lock`, and
# both matched. Observed live 2026-08-04: a 2.3 GB `.Z6B_4317-004.tmp` was
# re-downloaded to an editor on three consecutive passes because it changed
# between every one, and Resolve renames it away on completion, so not one of
# those bytes could ever be useful. `.partial` is rclone's own half-written
# marker; the .stignore builders already exclude it (server/common.py's
# PARTIAL_IGNORE_LINES, KNOWN_BUGS B12) but the rclone filters never did.
#
# No leading `/`: an rclone pattern with no slash matches the basename at any
# depth, the same way `+ *.mov` does in build_filter_rules_up. Case is
# handled by --ignore-case on the transfer commands.
IN_PROGRESS_EXCLUDE_RULES = ["- *.tmp", "- *.lock", "- *.partial"]

# macOS AppleDouble sidecars. On any filesystem WITHOUT native extended-
# attribute support -- exFAT, FAT32, SMB, i.e. exactly the external SSDs this
# deployment is built around -- macOS stores resource forks and xattrs in a
# sidecar file named `._<original>`, which KEEPS the original's extension. So
# `._A001.mov` matches lane A's `+ *.mov`, and a proxy-side `._p.mov` matches
# lane B's `+ **/Proxy/**`: a Mac editor published a junk sidecar beside every
# real clip into the shared tree, and lane B redistributed the proxy ones to
# everybody (KNOWN_BUGS 12, verified against the real binary 2026-08-04).
#
# FIRST in both rule lists, because rclone filter matching is first-match-wins
# and a later `+ *.mov` would otherwise win. One rule covers every depth: like
# IN_PROGRESS_EXCLUDE_RULES above it carries no `/`, so it matches the
# BASENAME anywhere in the tree -- measured against the bundled 1.74.4, this
# rule alone drops `._A001.mov`, `Proxy/._p.mov` and `Sub/Proxy/._n.mov`, so
# no companion `- **/._*` form is needed (unlike the `/Proxy/` rules, where
# the trailing `/**` anchors the pattern to a path and `**/` cannot match
# zero components).
#
# `.DS_Store` needs no rule: it matches no `+ *<ext>` and dies on the
# trailing `- **`.
APPLEDOUBLE_EXCLUDE_RULE = "- ._*"

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

# How long to wait for the stderr reader thread AFTER rclone itself has
# exited. Everything still unread is already sitting in the pipe buffer
# (64 KB at most) by then, so a healthy reader finishes in milliseconds --
# but the read only ends at EOF, and EOF only comes when the LAST holder of
# the write handle closes it. A grandchild that inherited it (an ssh helper,
# an AV shim) keeps the pipe open after rclone is gone, and an unbounded
# join() then blocked _run_once_locked forever WHILE HOLDING _run_lock,
# which stalls the sequencer's whole project rotation. Bounded: a truncated
# stderr tail is a far smaller loss than a wedged lane.
STDERR_READER_JOIN_SECONDS = 30.0

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

# -- lane B stability gate (2026-08-01) ------------------------------------
#
# The same gate on the download side, added for a failure the fleet actually
# hit. The Blackmagic Proxy Generator writes each proxy AT ITS FINAL NAME and
# grows it in place -- measured on the NAS: a 203 MB proxy spent 933 s that
# way -- while lane B was a 120 s periodic `sync` with no age check at all.
# It therefore sampled the same growing file ~7 times and shipped a truncated
# .mov every pass.
#
# It was not silent corruption: QuickTime writes the `moov` index LAST (these
# proxies are ftyp/wide/mdat/moov), so a truncated proxy has no index and
# simply won't open -- and the pass after generation finished repaired it.
# The damage was everything around that. Each partial was re-downloaded from
# byte 0 (~700 MB of transfer for that one 203 MB proxy), and every
# superseded copy was moved into <local_root>/.ccsync-trash by --backup-dir
# (verified: rclone backs up OVERWRITTEN files, not just deleted ones),
# firing "files moved to .ccsync-trash" toasts that blamed the wrong cause.
#
# --min-age is a STRONGER guard here than on lane A. Lane A's L-14 caveat is
# that Windows copy tools PRESERVE the source mtime, so a 40 GB .braw that
# landed a second ago can already look two hours old. A file being actively
# WRITTEN has a genuinely advancing mtime, which is exactly what --min-age
# reads. Set to 0 to disable the gate.
LANE_B_MIN_AGE_SECONDS = 120

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


class SpawnCancelled(RuntimeError):
    """stop() landed between "we decided to run rclone" and the spawn.

    Raised from inside the spawn critical section so the caller can tell a
    deliberate stand-down apart from a real failure: an orphaned rclone
    outlives the parent on Windows, so a self-upgrade that spawns here would
    leave the old process's upload racing the new process's lanes (AUDIT_2
    C-7 / KNOWN_BUGS B13). Never paints a lane red."""


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


def lane_b_min_age_seconds(cfg: Optional[dict]) -> int:
    """Lane B's stability gate, in seconds (0 = off).

    A module-level helper rather than an RcloneTuning field: tuning is
    transport shape (chunk sizes, concurrency), this is a correctness gate,
    and consolidate.py has to reach it for its --dry-run argv so the preview
    it shows the editor matches what the real run will actually do."""
    return max(0, _cfg_int(cfg, "lane_b_min_age_seconds", LANE_B_MIN_AGE_SECONDS))


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


# rclone filter patterns are globs: these characters carry meaning and must
# be escaped to match a literal filename. Backslash first -- it is the escape
# character itself, so escaping it after the others would double-escape them.
_FILTER_METACHARACTERS = "\\*?[]{}"


def escape_filter_pattern(text: str) -> str:
    """Quote a literal path for use as an rclone filter pattern.

    Real filenames in this tree contain `[`, `]` and `{` (`F:\\[BM Cloud]`,
    bracketed download names), and an unescaped one would silently turn into
    a character class matching the WRONG set of files -- in an exclude rule,
    that means skipping files nobody asked to skip.
    """
    return "".join("\\" + ch if ch in _FILTER_METACHARACTERS else ch for ch in str(text))


def build_filter_rules_up(exclude_paths: Optional[Iterable[str]] = None) -> list[str]:
    """Lane A: video files anywhere EXCEPT under a Proxy/ dir, nothing else.

    Both the nested (`**/Proxy/**`) and root-level (`/Proxy/**`) forms are
    needed: rclone's `**/` requires at least one leading path component, so
    a Proxy/ dir at the tree root would slip past the nested rule alone.

    `exclude_paths` are paths (relative to THIS run's source dir, `/`-separated)
    that the express lane is uploading right now -- see
    RcloneLane._express_inflight for why. They go FIRST because rclone filter
    matching is first-match-wins, so a later `+ *.mov` would otherwise win and
    the file would be uploaded twice concurrently.

    APPLEDOUBLE_EXCLUDE_RULE goes first of all, for the same first-match-wins
    reason -- `._A001.mov` ends in `.mov` and would otherwise be uploaded (see
    the constant). Ordering it against the express excludes is free: both are
    `-` rules, so whichever matches first reaches the same verdict.
    """
    rules = [APPLEDOUBLE_EXCLUDE_RULE]
    rules += [f"- /{escape_filter_pattern(rel)}" for rel in (exclude_paths or [])]
    rules += ["- **/Proxy/**", "- /Proxy/**"]
    rules += [f"+ *{ext}" for ext in VIDEO_EXTS]
    rules.append("- **")
    return rules


def build_filter_rules_down() -> list[str]:
    """Lane B: only the contents of Proxy/ dirs, at any depth (root included).

    The trash exclude comes FIRST (first-match-wins): the backup dir mirrors
    the source layout, so `.ccsync-trash/<ts>/Sub/Proxy/x.mov` matches
    `**/Proxy/**` and would otherwise be both re-deleted every pass and
    rejected by rclone's backup-dir overlap check.

    IN_PROGRESS_EXCLUDE_RULES come next, and before the `+ **/Proxy/**`
    include for the same first-match-wins reason: they are what stops the
    lane pulling a proxy Resolve is still writing (see the constant).

    APPLEDOUBLE_EXCLUDE_RULE is ahead of both. It has no ordering quarrel with
    them (all three are `-` rules), but it MUST beat `+ **/Proxy/**`, which
    matches every byte under a Proxy dir -- `._p.mov` included.
    """
    return [
        APPLEDOUBLE_EXCLUDE_RULE,
        TRASH_EXCLUDE_RULE,
        *IN_PROGRESS_EXCLUDE_RULES,
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


# -- the watchdog's own watchdog (MAC-12) ---------------------------------
#
# 2026-08-05, on the first editor Mac: the companion stopped dead one line
# after `lane_a_video_up: managed mode`. `sample` put the watchdog thread in
# `watchdog_add_watch -> FSEventStreamCreate -> watch_path -> open()`,
# blocked in the kernel for 100% of samples WHILE HOLDING THE GIL, on an
# external exFAT SSD whose FSEvents stream had wedged. Every other thread --
# tray, sign-in, main -- sat in take_gil, so the process was alive and did
# absolutely nothing until it was killed and the volume remounted.
#
# Nothing in-process can make that call safe: it is C code that takes the GIL
# and then blocks in the kernel, so "start the observer on another thread"
# moves the freeze, it does not avoid it. The one place an open() can hang
# without taking us with it is ANOTHER PROCESS. So before a root is handed to
# the observer, a short-lived subprocess opens and lists it; if that process
# cannot answer within a few seconds, the filesystem is not answering opens
# and the observer is not started. Lane A then uploads on the sequencer's
# schedule alone, and the tray, the sign-in and every other lane stay alive
# -- which is the entire difference from what happened on the Mac.
#
# Cross-platform on purpose. The FSEvents wedge is darwin's, but an SMB share
# whose server has gone, or a `subst` drive over one, is the same shape on
# Windows -- where the observer's first act is a CreateFileW on the root.
# The cost is one process per observer START (never per event), i.e. once at
# sign-in and once per retry.
WATCH_PROBE_TIMEOUT_SECONDS = 5.0
# First retry after a blocked probe, then doubling to the cap. A drive that
# is wedged stays wedged until someone unplugs it or reboots, so probing it
# every minute forever is just noise in the log.
WATCH_PROBE_RETRY_SECONDS = 60.0
WATCH_PROBE_MAX_RETRY_SECONDS = 900.0

# The probe answered in time -- whatever it answered. A root that does not
# exist, or that hands back EPERM promptly, is NOT this check's business:
# observer.schedule() fails cleanly on those and the root guard owns the
# story. The only thing being asked here is "does this filesystem answer?".
WATCH_PROBE_OK = "ok"
# It did not answer, so an open() on it can block forever.
WATCH_PROBE_BLOCKED = "blocked"
# We could not run a probe at all. Fails OPEN (see _watch_root_answers):
# refusing to watch the tree because our own probe is missing would be a
# self-inflicted outage.
WATCH_PROBE_UNAVAILABLE = "unavailable"

# Deliberately NOT an import of this package: the probe must start in
# milliseconds and must not run one line of the companion's import side
# effects. The open() is the exact call FSEvents blocked in; on Windows a
# directory cannot be os.open()ed, and the listdir is the equivalent (it is
# what ReadDirectoryChangesW's setup needs the handle for).
_WATCH_PROBE_SNIPPET = "\n".join((
    "import os, sys",
    "p = sys.argv[1]",
    "os.stat(p)",
    "os.listdir(p)",
    "if os.name == 'posix':",
    "    os.close(os.open(p, os.O_RDONLY))",
))


def watch_probe_command(
    root: str,
    executable: Optional[str] = None,
    frozen: Optional[bool] = None,
    is_windows: Optional[bool] = None,
) -> list[str]:
    """The argv of a process that opens `root` and then exits.

    In a frozen build `sys.executable` is the COMPANION, so `-c` there would
    start a second companion rather than a probe -- hence the base-system
    fallbacks, which are also the cheapest thing available on each platform.
    """
    exe = executable or sys.executable
    is_frozen = bool(getattr(sys, "frozen", False)) if frozen is None else bool(frozen)
    windows = (os.name == "nt") if is_windows is None else bool(is_windows)
    if not is_frozen:
        return [exe, "-c", _WATCH_PROBE_SNIPPET, str(root)]
    if windows:
        # Each piece its OWN argv element: `cmd /c "one long string"` is the
        # classic subprocess trap on Windows, because list2cmdline escapes an
        # embedded quote as \" and cmd.exe does not read \" that way -- the
        # probe would then fail instantly on a path with a space and never
        # touch the filesystem at all. `dir /b` exits 1 on an empty directory
        # and that is fine: the exit code is not what is being asked.
        comspec = os.environ.get("COMSPEC") or "cmd.exe"
        return [comspec, "/c", "dir", "/a", "/b", str(root)]
    return ["/bin/ls", "-a1", str(root)]


def _end_probe(proc: Any) -> None:
    """Kill a probe that never answered, without waiting on it forever.

    A process blocked in an uninterruptible kernel wait cannot be killed at
    all, and `subprocess.run(timeout=)` would sit in its post-kill
    communicate() -- which is the exact hang this whole mechanism exists to
    avoid, just moved into the check.
    """
    try:
        proc.kill()
    except Exception:
        log.debug("watch probe: could not kill the probe process", exc_info=True)
    try:
        proc.wait(timeout=1)
    except Exception:
        log.warning(
            "watch probe: the probe process is stuck in the kernel and could not be "
            "killed -- leaving it to the OS. That is another sign the volume is gone."
        )


def probe_watch_root(
    root: str,
    timeout: float = WATCH_PROBE_TIMEOUT_SECONDS,
    popen_factory: Optional[Callable[..., Any]] = None,
    command_fn: Callable[[str], list[str]] = watch_probe_command,
) -> tuple[str, str]:
    """Does `root`'s filesystem answer an open()? Returns (status, detail).

    Never raises, never blocks longer than `timeout` plus the kill, and never
    touches the path in THIS process -- which is the whole point.
    """
    try:
        cmd = command_fn(root)
    except Exception as exc:
        return WATCH_PROBE_UNAVAILABLE, f"could not build a probe command: {exc}"
    factory = popen_factory or subprocess.Popen
    try:
        proc = factory(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=_win_creationflags(),
        )
    except Exception as exc:
        return WATCH_PROBE_UNAVAILABLE, f"could not start a probe: {exc}"
    try:
        code = proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        _end_probe(proc)
        return WATCH_PROBE_BLOCKED, f"no answer within {timeout:.0f}s"
    except Exception as exc:
        _end_probe(proc)
        return WATCH_PROBE_UNAVAILABLE, f"the probe itself failed: {exc}"
    return WATCH_PROBE_OK, f"exit {code}"


# How many characters of rclone's stderr any single log line carries.
STDERR_LOG_CHARS = 300


def _stderr_for_log(stderr: Optional[str], limit: int = STDERR_LOG_CHARS) -> str:
    """The most informative `limit` characters of an rclone stderr stream.

    Two rules, both paid for live (KNOWN_BUGS 14, 2026-08-05):

    1. Drop NOTICE lines. Against any SFTP remote rclone opens with a host-key
       notice ~260 characters long, and `--stats-log-level NOTICE` adds a
       stats block on top -- neither says anything about why a run failed.
    2. Keep the TAIL, not the head. rclone puts the reason it died at the END
       of the stream; the head is banner noise.

    Taking the head of an unfiltered stream did both wrong at once, and an SSH
    auth failure that had stopped lanes A and B entirely reached the log as
    `CRITICAL: Failed to create file system for` and nothing else -- no
    remote, no reason. Finding it took a hand-run of the same command, which
    is exactly what the log line exists to avoid.
    """
    text = "\n".join(
        line for line in (stderr or "").splitlines() if "NOTICE:" not in line
    ).strip()
    if not text:
        # Nothing but notices: show them rather than logging a failure with no
        # text at all -- "it broke, no idea why" is the state we came from.
        text = (stderr or "").strip()
    return text[-limit:]


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
            "rclone lsf exited %d: %s", proc.returncode, _stderr_for_log(proc.stderr)
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


# rclone's DEFAULT Windows local encoding maps forbidden characters to their
# fullwidth forms (? -> ？) -- and QUOTES a name that already contains a
# fullwidth form by prefixing U+201B (‛). The tree is full of legitimate
# fullwidth punctuation (yt-dlp sanitizes YouTube titles that way), so lane B
# downloaded "…有完沒完？….mov" as "…有完沒完‛？….mov": byte-identical to
# rclone, but a DIFFERENT basename to Resolve, which matches proxies to clips
# by exact name -- 29 of one editor's 68 proxies could never relink
# (2026-07-26). This set is the default MINUS the punctuation mappings
# (LtGt, DoubleQuote, Colon, Question, Asterisk, Pipe), so fullwidth names
# round-trip verbatim in BOTH directions (lane A used to silently DE-encode
# ？ to a raw ? on the NAS, too). The trade: a NAS name containing a raw
# Windows-forbidden character now fails that file's transfer loudly instead
# of being silently renamed -- surveyed 2026-07-26: zero such names exist,
# and none can be created from Windows.
LOCAL_ENCODING = "Slash,BackSlash,Ctl,RightSpace,RightPeriod,InvalidUtf8,Dot"


def _transport_flags() -> list[str]:
    """Bounds on a stalled peer plus the filename-encoding pin, shared by
    every transfer command (lanes A/B and express).

    rclone's own idle default already covers most cases, but a peer that
    ACKs and then stalls (a Tailscale DERP flap, a hung TrueNAS SFTP
    subsystem) can otherwise hold _run_lock -- and therefore the whole
    sequencer -- forever (AUDIT_2 L-12). --retries-sleep stops a hot retry
    loop burning a whole pass while the tailnet flaps (§4.2)."""
    return [
        "--timeout", "5m",
        "--contimeout", "60s",
        "--retries-sleep", "10s",
        "--local-encoding", LOCAL_ENCODING,
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
    rule list: a video extension, no `Proxy` component at any depth, and no
    AppleDouble sidecar (APPLEDOUBLE_EXCLUDE_RULE) -- all case-insensitively,
    which is what --ignore-case buys the real run.
    test_rclone_filters.py proves the equivalence against the real binary.

    The sidecar check is here and not only in build_filter_rules_up because
    express is lane A's OTHER door: `._A001.mov` ends in `.mov` and sits in no
    Proxy dir, so without it a Mac's watchdog event would upload the very file
    the periodic pass now refuses (KNOWN_BUGS 12).
    """
    if not path:
        return False
    if os.path.splitext(path)[1].lower() not in VIDEO_EXTS:
        return False
    parts = [seg for chunk in str(path).split("/") for seg in chunk.split("\\")]
    if parts and parts[-1].startswith("._"):
        return False
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
    min_age_seconds: int = LANE_B_MIN_AGE_SECONDS,
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
    if min_age_seconds > 0:
        # See LANE_B_MIN_AGE_SECONDS. Without this, a proxy still being
        # written on the NAS is shipped truncated, once per pass, and each
        # superseded partial is swept into .ccsync-trash by --backup-dir
        # below. MUST stay ahead of that flag in argv order only for
        # readability -- rclone does not care, humans reading a logged
        # command line do.
        cmd += ["--min-age", f"{int(min_age_seconds)}s"]
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


# rclone's closing notice when any fatal error occurred. It is the LAST
# error line, printed after the actual cause -- surfacing it verbatim gave
# the tray "Fatal error received - not attempting retries" with the real
# reason buried in a log too long to read (2026-07-26).
_FATAL_NOTICE = "fatal error received"
# rclone's own level names for "this run is in trouble" (SYNC-11).
_ERROR_LEVELS = ("error", "critical", "fatal")
# The per-file line --backup-dir writes instead of a delete.
_BACKUP_MOVE = "into backup dir"


def _most_informative_error(errors: list) -> str:
    """The error line most worth showing a human: the first line that is
    NOT the generic fatal-notice, else whatever exists."""
    for line in errors:
        if _FATAL_NOTICE not in str(line).lower():
            return str(line)
    return str(errors[-1]) if errors else ""


def _is_max_delete_abort(errors: list) -> bool:
    """Did this run stop because --max-delete/--max-delete-size tripped?"""
    return any("max-delete" in str(line).lower() or "max delete" in str(line).lower()
               for line in errors)


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
    # Per-file names rclone reported as Copied/Moved this run (bounded, see
    # RcloneRunTally.MAX_COMPLETED) -- the transfer HISTORY the dashboard
    # shows; requested 2026-07-26.
    completed_files: list = field(default_factory=list)


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
    # Newest completions win when a run moves more than this.
    MAX_COMPLETED = 200

    def __init__(self) -> None:
        self.transferred = 0
        self.deleted = 0
        self.error_count = 0
        self._errors: deque[str] = deque(maxlen=self.MAX_ERRORS)
        self._completed: deque[str] = deque(maxlen=self.MAX_COMPLETED)

    def feed_record(self, record: dict) -> None:
        level = record.get("level", "")
        msg = record.get("msg", "")
        if level in _ERROR_LEVELS:
            # SYNC-11 (2026-08-11): only level == "error" was recorded, so the
            # `Failed to create file system for ...` shape -- which rclone logs
            # at CRITICAL before exiting -- left `errors` empty. That blinded
            # both _most_informative_error (which then returned "") and
            # _is_max_delete_abort, whose whole job is reading these lines.
            self.error_count += 1
            self._errors.append(msg)
        elif isinstance(record.get("stats"), dict):
            # SYNC-10 (2026-08-11): a --stats tick's msg is the WHOLE run
            # summary, and it carries "Deleted: N (files)" from the first
            # deletion onwards -- so every tick was counted as one more
            # transferred AND one more deleted file. A lane B pass that
            # trashed 12 proxies over ten minutes reported ~300 deletions to
            # the dashboard. Stats records describe the run, never a file.
            return
        elif "Copied" in msg or "Moved" in msg or "Deleted" in msg:
            # Per-file records ("clip.mov: Copied (new)") only — the run-
            # summary stats line ("Transferred: 0 B / ...") must not count
            # as a file, which is why "Transferred" is NOT matched here.
            self.transferred += 1
            if "Deleted" in msg or _BACKUP_MOVE in msg:
                # --backup-dir does not delete, it moves aside ("clip.mov:
                # Moved into backup dir") -- but from the destination's point
                # of view the file is gone, and counting it as a completion
                # put it in the dashboard's transfer HISTORY as if it had just
                # arrived (SYNC-10).
                self.deleted += 1
            else:
                # "object" is the file path relative to the transfer root
                # ("B-roll/.../clip.mov") in rclone's per-file records.
                name = str(record.get("object") or "")
                if name:
                    self._completed.append(name)

    def result(self) -> RcloneRunResult:
        return RcloneRunResult(
            ok=not self.error_count,
            transferred=self.transferred,
            errors=list(self._errors),
            raw_returncode=0,
            error_count=self.error_count,
            deleted=self.deleted,
            completed_files=list(self._completed),
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


# -- project identity for a transfer row -----------------------------------
#
# The dashboard's `transfers.project_slug` column (api.TransferIn ->
# db.replace_active_transfers) was always NULL: it accepts and persists the
# field, and the companion never sent it, so a live transfer could only ever
# be shown by file path. The slug is the project's IMMUTABLE identity from
# its .ccsync-project marker -- it survives a rename/move on the NAS, which
# a rel path does not, so it is the only stable key to join a transfer row
# to a project.
#
# Intentional copy of dashboard provision.MARKER_FILENAME/SLUG_RE/read_marker
# (and fixer.MARKER_FILENAME) rather than an import: this module deliberately
# depends on nothing above sync/, and fixer pulls in resolve_bridge. Same
# duplication posture as VIDEO_EXTS above -- keep them in sync.
MARKER_FILENAME = ".ccsync-project"
# A marker is a plain JSON file on a share every editor can write, and this
# value crosses the wire into a dashboard URL segment/Syncthing folder id, so
# a hand-dropped {"slug": "../../etc"} must not get that far.
SLUG_RE = re.compile(r"^[a-z0-9-]+$")
# The dashboard declares `project_slug: str | None = Field(max_length=128)`
# on TransferIn, and pydantic rejects the WHOLE report body on a violation --
# which would take lane status, presence and the upgrade advertisement down
# with it, for a cosmetic field. Nothing upstream bounds a marker slug's
# length, so the sender does: over the cap, the field is simply omitted.
MAX_PROJECT_SLUG_CHARS = 128


def read_project_slug(directory) -> Optional[str]:
    """The .ccsync-project marker's slug for a project dir, or None.

    None for missing/unreadable/malformed markers and for a slug that fails
    SLUG_RE -- callers treat that as "no attribution" and omit the field
    rather than sending a guess. Never raises."""
    try:
        raw = (Path(directory) / MARKER_FILENAME).read_text(encoding="utf-8-sig")
        slug = str(json.loads(raw).get("slug", "")).strip()
    except (OSError, ValueError, AttributeError, TypeError):
        return None
    if not slug:
        return None
    if not SLUG_RE.match(slug):
        log.debug(
            "ignoring the project marker in %s: slug %r is not a valid identity",
            directory, slug,
        )
        return None
    return slug


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
        log.debug("express/watchdog: %r is outside local_root %r", path, local_root)
        return None
    parts = rel.parts
    # Case-INSENSITIVE, like every other comparison in this function (and
    # like the --ignore-case both lanes run with): a mapped `P:\projects\...`
    # or a local_root the editor typed in lower case used to fail this one
    # literal check while the rest of the path was lowercased anyway, so the
    # file silently waited for the next full rotation with nothing logged.
    if len(parts) < 2 or parts[0].lower() != "projects":
        log.debug(
            "express/watchdog: %r is not under a 'Projects' directory of %r -- "
            "the periodic pass owns it", path, local_root,
        )
        return None
    inner = [p.lower() for p in parts[1:]]

    if known_rels is not None:
        best: Optional[str] = None
        best_len = 0
        for known in known_rels:
            segs = [s.lower() for s in known.strip("/").split("/") if s]
            if len(segs) < len(inner) and inner[: len(segs)] == segs and len(segs) > best_len:
                best, best_len = known, len(segs)
        if not best:
            log.debug(
                "express/watchdog: %r matches none of the %d known project rel(s)",
                path, len(known_rels),
            )
            return None
        return f"Projects/{best}"

    if len(parts) < 4:
        log.debug(
            "express/watchdog: %r is above the legacy year/series/project depth", path
        )
        return None
    # "Projects" spelled canonically, not as it happens to be cased on disk:
    # this string becomes an rclone subpath on the NAS, which IS case
    # sensitive.
    return "/".join(["Projects", *parts[1:4]])


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
        on_watch_blocked: Optional[Callable[[str], None]] = None,
        watch_probe_fn: Optional[Callable[[str], tuple[str, str]]] = None,
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
        # Called with one sentence for the editor when lane A's file watcher
        # could not be started because the sync drive stopped answering
        # (MAC-12), and again when it comes back. Same shape again.
        self.on_watch_blocked = on_watch_blocked
        # The pre-flight that keeps a blocking open() out of THIS process --
        # see probe_watch_root. Injectable so the tests can drive success,
        # failure and a wedged volume without one.
        self._watch_probe = watch_probe_fn or probe_watch_root
        # Selected-project rels (any depth) for the watchdog's project
        # attribution -- see _project_rel_for_path. None = legacy heuristic.
        self.known_rels_fn = known_rels_fn
        # Transport tuning (AUDIT_2 P1/P2/§4.2). `cfg` is optional so a
        # caller that doesn't pass one still gets the recommended defaults
        # rather than rclone's -- the flags are the fix, config is only the
        # override seam (C-5).
        self.tuning = RcloneTuning.from_cfg(cfg)
        # Lane B only -- keeps a proxy that is still being written on the NAS
        # out of the run entirely (see LANE_B_MIN_AGE_SECONDS).
        self.min_age_seconds = lane_b_min_age_seconds(cfg)
        # Last orphan-.partial scan (P8/P15/C-7): REPORTED, never deleted.
        self._orphans: Optional[dict] = None
        # subpath -> marker slug, for the project_slug on each transfer row.
        # POSITIVE results only: a project dir whose marker hasn't synced down
        # yet (lane C delivers it) must not be remembered as "no slug" for the
        # life of the process. A slug is immutable and travels with its
        # directory, so a cached one can never go stale -- a move changes the
        # subpath, i.e. the cache key.
        self._project_slug_cache: dict[str, str] = {}
        # Warn-once latch for the missing-local_root refusal below: the
        # periodic loop, the debounce timer and the sequencer all call
        # run_once(), so an unplugged drive would otherwise write a WARNING
        # every few seconds for as long as it stays out.
        self._root_missing_logged = False

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
        # Held across "check the stop flag -> spawn -> publish the handle",
        # and taken again by _kill_running_process. Without it there was a
        # window in which stop() looked at _proc, found None (the child was
        # about to be created), returned -- and the spawn then started an
        # rclone that outlived the parent (KNOWN_BUGS B13). Never held while
        # waiting on the child.
        self._proc_lock = threading.Lock()
        self._observer = None  # watchdog Observer, lane A only
        self._debounce_timer: Optional[threading.Timer] = None
        # Watcher pre-flight state (MAC-12): the re-check timer, how long the
        # next wait is, and whether the editor has already been told. The
        # latch is what keeps a wedged drive to ONE toast rather than one per
        # retry for as long as it stays wedged.
        self._watch_retry_timer: Optional[threading.Timer] = None
        self._watch_retry_delay = WATCH_PROBE_RETRY_SECONDS
        self._watch_blocked_announced = False
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
        # Paths the CURRENT express run has in flight, so the periodic pass
        # can filter them out instead of racing it for the same bytes (see
        # _build_command). Its own lock: _build_command reads this from the
        # periodic thread while the express thread is writing it, and it must
        # not queue behind either of the run locks.
        self._express_inflight: set[str] = set()
        self._express_inflight_lock = threading.Lock()
        self._express_lock = threading.Lock()  # guards the pending map/timer
        # rel(posix) -> (last observed size, first seen monotonic)
        self._express_pending: dict[str, tuple[int, float]] = {}
        self._express_timer: Optional[threading.Timer] = None
        self._express_proc = None
        # The express twin of _proc_lock: _express_stop() must never be able
        # to look for a child in the instant between "the shutdown flag was
        # last checked" and "the handle is published" (KNOWN_BUGS B13).
        self._express_proc_lock = threading.Lock()
        self._express_shutdown = threading.Event()
        # "Pause syncing" (tray) -- distinct from _express_shutdown, which is
        # latched off by stop() for a whole thread generation. See
        # pause_express().
        self._express_paused = threading.Event()
        self._express_seq = 0
        # Lane B's --backup-dir for the run in flight (see _notify_trash).
        self._last_backup_dir: Optional[str] = None
        # Completed-file events awaiting the next report (the dashboard's
        # transfer HISTORY). Bounded; drained by pop_completions().
        self._pending_completions: deque = deque(maxlen=400)
        # Monotonic stamp of the last trash TOAST, None until the first. A
        # large cleanup is spread across passes by --max-delete-size, and a
        # toast per pass for one continuing event trained the editor to
        # dismiss it unread (2026-07-26, the ‛-name transition). The log
        # line stays per-run. (None, not 0.0: monotonic() starts near zero
        # on a fresh boot, and 0.0 would swallow the FIRST toast.)
        self._last_trash_notify_at: Optional[float] = None
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
    def _ensure_filter_file(self, exclude_paths: Optional[Iterable[str]] = None) -> Path:
        rules = (
            build_filter_rules_up(exclude_paths)
            if self.direction == DIRECTION_UP
            else build_filter_rules_down()
        )
        return write_filter_file(rules, self._filter_file)

    def express_inflight_paths(self) -> list[str]:
        """Snapshot of what the express lane is uploading right now
        (local_root-relative, `/`-separated). Sorted so the filter file is
        deterministic for a given set."""
        with self._express_inflight_lock:
            return sorted(self._express_inflight)

    @staticmethod
    def _relativize_to_subpath(rel: str, subpath: Optional[str]) -> Optional[str]:
        """Re-express a local_root-relative express path against this run's
        source dir (`local_root/subpath`), or None when it falls outside.

        Lane A copies `local_root/<subpath>`, so its filter patterns are
        anchored there, while express paths are always local_root-relative.
        Compared case-insensitively because lane A runs --ignore-case and the
        two strings can differ only in the casing of a shared parent.
        """
        clean = str(rel or "").replace("\\", "/").strip("/")
        if not clean:
            return None
        sub = str(subpath or "").replace("\\", "/").strip("/")
        if not sub:
            return clean
        if clean.lower() == sub.lower():
            return None  # the subpath itself is a directory, not a file
        prefix = sub.lower() + "/"
        if not clean.lower().startswith(prefix):
            return None  # a different project -- this run would never see it
        return clean[len(prefix):] or None

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
        if self.direction == DIRECTION_UP:
            # Don't re-upload what express already has in flight. Both runs
            # use --ignore-existing, but neither has finished, so the
            # destination doesn't exist yet for either to skip -- measured on
            # an editor's machine 2026-08-02, the same .mov climbing on two
            # concurrent connections and splitting a saturated uplink between
            # them. Express wins the race by design (it is the low-latency
            # path); anything it drops is still missing next pass, so this
            # loses nothing.
            excludes = [
                rel for rel in (
                    self._relativize_to_subpath(p, subpath)
                    for p in self.express_inflight_paths()
                ) if rel
            ]
            if excludes:
                log.info(
                    "%s: deferring %d path(s) to the in-flight express run",
                    self.name, len(excludes),
                )
            filter_file = self._ensure_filter_file(excludes)
            return build_up_command(
                self.rclone_path, self.local_root, self.remote, self.remote_root,
                filter_file, self.transfers, subpath=subpath, stats_interval=stats_interval,
                max_duration_seconds=max_duration_seconds, tuning=self.tuning,
            )
        filter_file = self._ensure_filter_file()
        # Remembered so the run can tell the editor WHERE its files went --
        # see _notify_trash. Safe as instance state: run_once holds _run_lock,
        # and only lane A has the (separately locked) express path.
        backup_dir = self._backup_dir(subpath)
        self._last_backup_dir = backup_dir
        return build_down_command(
            self.rclone_path, self.local_root, self.remote, self.remote_root,
            filter_file, self.transfers, subpath=subpath, stats_interval=stats_interval,
            backup_dir=backup_dir, max_duration_seconds=max_duration_seconds,
            tuning=self.tuning, min_age_seconds=self.min_age_seconds,
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
        # OBSERVER FIRST, TIMER SECOND (legacy whole-tree mode). The other
        # order left a window: cancel the timer, then a file event still
        # being delivered by the live observer called
        # _schedule_debounced_run() -- which arms a NEW timer under _lock,
        # a lock stop() wasn't holding -- and run_once() fired on a stopped
        # lane seconds later. Stopping and JOINING the observer first means
        # no handler can still be in flight; _schedule_debounced_run's own
        # _stop_event check (also under _lock) closes what the join cannot.
        if self._observer is not None:
            try:
                self._observer.stop()
                self._observer.join(timeout=5)
            except Exception:
                pass
            self._observer = None
        with self._lock:
            timer, self._debounce_timer = self._debounce_timer, None
            # The MAC-12 re-check timer goes the same way: a lane that was
            # never allowed to start its watcher must not wake up a minute
            # after shutdown and start one.
            watch_retry, self._watch_retry_timer = self._watch_retry_timer, None
        if timer is not None:
            timer.cancel()
        if watch_retry is not None:
            watch_retry.cancel()
        # A fresh generation gets a fresh backoff: this lane may be stopping
        # precisely because the editor is about to replug the drive.
        self._watch_retry_delay = WATCH_PROBE_RETRY_SECONDS

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
        # Read the handle under the SPAWN lock, not bare. The shutdown flag
        # above is set before we take it, so the two possible interleavings
        # are now both safe: either we get the lock first (and the spawn
        # about to happen sees the flag and stands down), or the spawner got
        # it first (and by the time we have it, _express_proc is published
        # and we can terminate it). Before this, "None" simply meant "the
        # child is a microsecond away from existing" (KNOWN_BUGS B13).
        with self._express_proc_lock:
            proc = self._express_proc
            if proc is None:
                return
            self._terminate_child(proc, "express rclone")

    def _kill_running_process(self) -> None:
        with self._proc_lock:
            proc = self._proc
            if proc is None:
                return
            self._terminate_child(proc, "rclone")

    def _terminate_child(self, proc, what: str) -> None:
        """terminate -> wait -> kill, never raising. Shared by both stop
        paths; the caller holds the matching spawn lock."""
        try:
            if proc.poll() is not None:
                return
            log.info("%s: terminating in-flight %s on stop()", self.name, what)
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except Exception:
                proc.kill()
        except Exception:
            log.debug("%s: could not terminate the %s child", self.name, what, exc_info=True)

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

    # -- the tree has to actually be there --------------------------------
    def _local_root_is_present(self) -> bool:
        """Is local_root a directory right now?

        Fails OPEN (True) if the probe itself raises, which os.path.isdir
        effectively never does -- it already swallows OSError and answers
        False. The alternative, treating an unanswerable probe as "absent",
        would let one exotic filesystem error stop an editor syncing with no
        way to override it."""
        try:
            present = os.path.isdir(str(self.local_root))
        except Exception:
            log.debug("%s: could not check local_root", self.name, exc_info=True)
            return True
        if present:
            # Re-arm the warning, so a SECOND disconnect is reported too.
            self._root_missing_logged = False
        return present

    def _note_local_root_missing(self) -> None:
        """Park the lane idle with a detail an editor can act on."""
        with self._lock:
            self._status.state = STATE_IDLE
            self._status.detail = "local root missing (drive disconnected?)"
            self._status.transferring = 0
            self._status.current_project = None
        if not self._root_missing_logged:
            self._root_missing_logged = True
            log.warning(
                "%s: not running -- local_root %s is not a directory. If this is an "
                "external drive, plug it back in; syncing resumes on its own.",
                self.name, self.local_root,
            )

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
        # THE SAFETY LINE, and it is first for a reason. This lane is
        # `rclone sync <NAS> <local_root>` in the DOWN direction. Against a
        # local_root that is not there -- a macOS editor's external SSD
        # unplugged, an unmounted drive letter -- rclone does not fail: it
        # CREATES the destination and fills the machine's internal disk with
        # the project that was supposed to live on the SSD. Up-direction is no
        # better: an empty source against a `copy` is a no-op today, but it is
        # one refactor away from being a mirror. app.py's root guard normally
        # pauses the lanes long before this, and this check is what holds if
        # that guard's thread ever dies.
        if not self._local_root_is_present():
            self._note_local_root_missing()
            return self.status()
        # A stopped lane must not START a run. run_once() is called from the
        # periodic loop, the debounce timer AND (in managed mode) the
        # sequencer, none of which can be sure stop() didn't land while they
        # were queued on _run_lock -- and everything below this point ends in
        # a spawned rclone that outlives the parent on Windows (KNOWN_BUGS
        # B13). Cheap and re-checked again immediately before the spawn,
        # because rclone_available() and _build_command() take real time.
        if self._stop_event.is_set():
            log.debug("%s: run skipped -- the lane is stopping", self.name)
            return self.status()

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

        # 2s, not 10s: this feeds the per-file progress the dashboard and
        # tray show, and with a 10s tick the end-to-end staleness (stats +
        # 5s report + page poll) reached ~18s -- bars that "update really
        # slowly". Parsing one small JSON line every 2s is negligible.
        stats_interval = None if self._legacy_run else "2s"
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
                # Same guard as the Popen path, minus the handle: this seam
                # blocks in subprocess_run and hands back a finished process,
                # so there is nothing for stop() to kill -- the pre-spawn
                # check is the only cancellation point it has.
                with self._proc_lock:
                    self._raise_if_stopping("run")
                proc = self.subprocess_run(
                    cmd,
                    capture_output=True,
                    timeout=None,
                    encoding="utf-8",
                    errors="replace",
                    creationflags=_win_creationflags(),
                )
            except SpawnCancelled:
                return self._stand_down_status()
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
            except SpawnCancelled:
                return self._stand_down_status()
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

        self._record_completions(result, subpath)

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
            elif returncode != 0 and _is_max_delete_abort(result.errors):
                # The --max-delete/--max-delete-size safety valve tripped:
                # rclone exits FATAL, but this is the cap doing its job --
                # one oversized cleanup (the 2026-07-26 ‛-name transition
                # moved ~30 GB in 20 GB slices) is throttled across passes,
                # not broken. Painting the lane red said "Something went
                # wrong" for hours of correct behavior.
                log.info(
                    "%s: delete safety cap reached this pass -- the cleanup "
                    "continues next pass (%s)", self.name,
                    result.errors[0] if result.errors else "",
                )
                self._status.state = STATE_IDLE
                self._status.last_error = None
                self._status.last_sync = datetime.now(timezone.utc)
                self._status.detail = (
                    f"transferred {result.transferred} file(s); tidying old files "
                    "in slices (safety cap), continues next pass"
                )
            elif returncode != 0:
                self._status.state = STATE_ERROR
                self._status.last_error = (
                    _most_informative_error(result.errors)
                    or _stderr_for_log(stderr_text)
                    or f"rclone exited {returncode}"
                )
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

    def _record_completions(self, result: RcloneRunResult, subpath: Optional[str]) -> None:
        """Queue this run's per-file completions for the next report -- the
        dashboard's transfer HISTORY (requested 2026-07-26; before this,
        finished files vanished from the live table with no trace). Names
        are made project-relative-from-Projects/ when a subpath is known so
        they read like every other path on the dashboard. Never raises."""
        try:
            if not result.completed_files:
                return
            at = datetime.now(timezone.utc).isoformat()
            prefix = f"{subpath.strip('/')}/" if subpath else ""
            for name in result.completed_files:
                self._pending_completions.append({
                    "name": f"{prefix}{name}",
                    "direction": self.direction,
                    "lane": self.name,
                    "at": at,
                })
        except Exception:
            log.debug("%s: recording completions failed", self.name, exc_info=True)

    def pop_completions(self) -> list[dict]:
        """Drain the completed-file events (reporter thread). Never raises."""
        out: list[dict] = []
        try:
            while self._pending_completions:
                out.append(self._pending_completions.popleft())
        except Exception:
            log.debug("%s: pop_completions failed", self.name, exc_info=True)
        return out

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
        now = time.monotonic()
        if (self._last_trash_notify_at is not None
                and now - self._last_trash_notify_at < TRASH_NOTIFY_COOLDOWN_SECONDS):
            return
        self._last_trash_notify_at = now
        try:
            self.on_trash(str(backup_dir))
        except Exception:
            log.exception("%s: on_trash callback failed", self.name)

    # -- spawn cancellation (KNOWN_BUGS B13) ------------------------------
    def _raise_if_stopping(self, what: str) -> None:
        """Stand down if stop() has landed. Caller holds the spawn lock."""
        if self._stop_event.is_set():
            log.info(
                "%s: %s cancelled -- stop() landed before rclone was started",
                self.name, what,
            )
            raise SpawnCancelled(f"{self.name}: {what} cancelled by stop()")

    def _stand_down_status(self) -> LaneStatus:
        """Clear the SYNCING bookkeeping a cancelled run had already set.

        Deliberately IDLE, not ERROR: a lane that was told to stop did not
        fail, and painting it red would make every self-upgrade/sign-out look
        like a broken lane on the grid."""
        with self._lock:
            self._status.state = STATE_IDLE
            self._status.transferring = 0
            self._status.speed_bps = None
            self._status.eta_seconds = None
            self._status.transfers = []
            self._status.current_project = None
            self._status.detail = "stopped before this pass started"
        return self.status()

    # -- Popen-based runner with live --stats JSON parsing ---------------
    def _run_popen(self, cmd: list[str]) -> tuple[int, str, RcloneRunResult]:
        """Run rclone, parsing its stderr AS IT ARRIVES.

        Returns (returncode, bounded stderr tail, incremental parse result).
        The tail is STDERR_TAIL_LINES lines, not the whole stream: see
        RcloneRunTally for why keeping all of it was a memory problem on real
        ingests (AUDIT_3 M-8)."""
        factory = self.popen_factory or subprocess.Popen
        # SPAWN AND PUBLISH ATOMICALLY. _kill_running_process() takes the
        # same lock, so it can no longer see `_proc is None` for a child that
        # is about to exist and return having killed nothing (KNOWN_BUGS
        # B13). The lock is released before proc.wait(), so stop() is never
        # blocked for longer than a spawn.
        with self._proc_lock:
            self._raise_if_stopping("run")
            proc = factory(
                cmd,
                stderr=subprocess.PIPE,
                encoding="utf-8",
                errors="replace",
                creationflags=_win_creationflags(),
            )
            # Published so stop() can end this child instead of orphaning it.
            self._proc = proc
        tail: deque[str] = deque(maxlen=STDERR_TAIL_LINES)
        tally = RcloneRunTally()
        # Set when the reader is abandoned (see the join below): a reader
        # still blocked on a pipe a grandchild is holding open must not go on
        # writing this run's status/tally into the NEXT run's.
        abandoned = threading.Event()

        def _reader() -> None:
            # Never let a decode/IO error escape this thread: with no
            # try/except here, one non-ASCII filename raising inside the
            # loop would kill the reader silently, nobody would drain
            # proc.stderr, rclone would block on a full pipe once its 64 KB
            # buffer fills, and proc.wait() below would never return --
            # deadlocking _run_lock (and the whole sequencer) forever.
            try:
                for line in proc.stderr:
                    if abandoned.is_set():
                        return
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
        try:
            returncode = proc.wait()
        finally:
            with self._proc_lock:
                if self._proc is proc:
                    self._proc = None
        # BOUNDED (see STDERR_READER_JOIN_SECONDS): rclone has exited, so a
        # reader that is still blocked is waiting on a write handle some
        # grandchild inherited and will never close. Waiting forever here
        # wedged _run_lock and with it the sequencer's rotation.
        reader_thread.join(timeout=STDERR_READER_JOIN_SECONDS)
        if reader_thread.is_alive():
            abandoned.set()
            log.warning(
                "%s: rclone exited but its stderr pipe is still open after %.0fs "
                "(a grandchild inherited the write handle) -- continuing with a "
                "truncated log tail rather than blocking the lane",
                self.name, STDERR_READER_JOIN_SECONDS,
            )
        try:
            tail_text = "".join(list(tail))
            result = tally.result()
        except RuntimeError:
            # An abandoned reader mutated a deque mid-snapshot. Both are
            # diagnostics/counters for a run that has already finished, so a
            # partial answer beats raising into the lane's error state.
            tail_text = ""
            result = RcloneRunTally().result()
        return returncode, tail_text, result

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
        # The project this run is for, read and released before resolving the
        # slug: that can touch the disk (the marker), and _lock is on the
        # tray's and the reporter's read path.
        with self._lock:
            subpath = self._status.current_project
        project_slug = self._project_slug_for_subpath(subpath)
        with self._lock:
            self._status.bytes_done = stats.get("bytes")
            self._status.bytes_total = stats.get("totalBytes")
            self._status.speed_bps = stats.get("speed")
            self._status.eta_seconds = stats.get("eta")
            self._status.transfers = self._normalize_transferring(
                stats.get("transferring"), project_slug
            )

    def _project_slug_for_subpath(self, subpath: Optional[str]) -> Optional[str]:
        """The marker slug for this run's project, or None.

        None for a whole-tree run (no subpath) and for a project whose marker
        hasn't arrived yet -- callers omit the field entirely in that case
        rather than inventing one from the rel path, which is exactly the
        guess the slug exists to avoid (a renamed project keeps its slug and
        changes its rel). Never raises."""
        key = str(subpath or "").strip().strip("/").replace("\\", "/")
        if not key:
            return None
        cached = self._project_slug_cache.get(key)
        if cached is not None:
            return cached
        try:
            slug = read_project_slug(Path(self.local_root) / Path(*key.split("/")))
        except Exception:
            log.debug("%s: could not read the project marker for %s", self.name, key,
                      exc_info=True)
            return None
        if slug and len(slug) > MAX_PROJECT_SLUG_CHARS:
            log.warning(
                "%s: not reporting project_slug for %s -- %d chars exceeds the "
                "%d the dashboard accepts, and an over-long value would 422 the "
                "whole report", self.name, key, len(slug), MAX_PROJECT_SLUG_CHARS,
            )
            return None
        if slug:
            self._project_slug_cache[key] = slug
        return slug

    def _normalize_transferring(
        self, transferring: Optional[list], project_slug: Optional[str] = None
    ) -> list[dict]:
        """Normalize rclone --stats JSON's "transferring" array (per-file, live
        mid-transfer only -- absent/empty between files or once idle) into the
        dashboard's "transfers" shape. Direction is fixed per-lane.

        `project_slug` is the dashboard's TransferIn.project_slug (persisted
        by db.replace_active_transfers). The KEY IS OMITTED when the lane has
        no project attribution -- a whole-tree run, or a project dir whose
        marker hasn't synced down yet -- so the column stays NULL instead of
        carrying a guessed identity."""
        direction = DIRECTION_UP if self.direction == DIRECTION_UP else DIRECTION_DOWN
        if not transferring:
            return []
        result: list[dict] = []
        for entry in transferring:
            if not isinstance(entry, dict):
                continue
            row = {
                "name": entry.get("name"),
                "direction": direction,
                "bytes_done": entry.get("bytes"),
                "bytes_total": entry.get("size"),
                "percentage": entry.get("percentage"),
                "speed_bps": entry.get("speed"),
                "eta_seconds": entry.get("eta"),
            }
            if project_slug:
                row["project_slug"] = project_slug
            result.append(row)
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

        # BEFORE anything touches local_root from this process (MAC-12).
        if not self._watch_root_answers():
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
            return
        self._note_watchdog_started()

    # -- the watchdog's own watchdog (MAC-12) ------------------------------

    def _watch_root_answers(self) -> bool:
        """Can a SEPARATE process open and list local_root, promptly?

        The reasoning is in the module comment above probe_watch_root: the
        observer's first act on this root is an open() from C code holding
        the GIL, and against a filesystem that has stopped answering it
        freezes the ENTIRE companion -- tray, sign-in, main thread and all.
        A subprocess is the only place that open is allowed to hang.

        False means "do not start the observer"; a re-check has already been
        scheduled and the editor has already been told.
        """
        try:
            status, detail = self._watch_probe(self.local_root)
        except Exception as exc:
            # A broken probe must never cost the lane its watcher.
            log.debug("%s: watch pre-flight raised (%s) -- starting the watcher anyway",
                      self.name, exc)
            return True
        if status == WATCH_PROBE_UNAVAILABLE:
            log.debug(
                "%s: could not pre-flight %s (%s) -- starting the watcher anyway",
                self.name, self.local_root, detail,
            )
            return True
        if status != WATCH_PROBE_BLOCKED:
            return True

        delay = self._watch_retry_delay
        log.error(
            "%s: the sync drive's filesystem is not answering -- a separate test "
            "process could not open %s (%s). NOT starting the file watcher: it opens "
            "that path from C code holding the GIL, and a blocked open there freezes "
            "the whole companion, tray and sign-in included (MAC-12). Disconnect and "
            "reconnect the drive, or restart the computer. Uploads still run on the "
            "sequencer's schedule; this is re-checked in %.0fs.",
            self.name, self.local_root, detail, delay,
        )
        if not self._watch_blocked_announced:
            self._watch_blocked_announced = True
            self._announce_watch_state(
                "The sync drive isn't responding, so CCSync can't watch it for new "
                "files. Disconnect and reconnect the drive, or restart the computer. "
                "Everything else is still running."
            )
        self._schedule_watch_retry(delay)
        return False

    def _note_watchdog_started(self) -> None:
        """The observer is up. If the drive had stopped answering, say so --
        a remount fixes this without a restart and the editor should hear
        that it took, not be left wondering."""
        self._watch_retry_delay = WATCH_PROBE_RETRY_SECONDS
        if not self._watch_blocked_announced:
            return
        self._watch_blocked_announced = False
        log.info("%s: the sync drive is answering again -- the file watcher is back",
                 self.name)
        self._announce_watch_state("The sync drive is responding again — CCSync is watching it for "
                  "new files.")

    def _announce_watch_state(self, message: str) -> None:
        callback = self.on_watch_blocked
        if callback is None:
            return
        try:
            callback(message)
        except Exception:
            log.exception("%s: could not surface the watcher's state", self.name)

    def _schedule_watch_retry(self, delay: float) -> None:
        with self._lock:
            # Under _lock, which stop() also takes to disarm this timer --
            # same reasoning as _schedule_debounced_run: without it a retry
            # armed just after stop() cancelled the old one would start an
            # observer on a stopped lane a minute later.
            if self._stop_event.is_set():
                return
            if self._watch_retry_timer is not None:
                self._watch_retry_timer.cancel()
            timer = threading.Timer(delay, self._retry_watchdog)
            timer.daemon = True
            self._watch_retry_timer = timer
            timer.start()
        self._watch_retry_delay = min(delay * 2, WATCH_PROBE_MAX_RETRY_SECONDS)

    def _retry_watchdog(self) -> None:
        with self._lock:
            self._watch_retry_timer = None
        # cancel() only helps before the deadline, so the stop check is
        # repeated here (exactly as _debounced_fire does).
        if self._stop_event.is_set() or self._observer is not None:
            return
        log.info("%s: re-checking whether the sync drive is answering", self.name)
        try:
            self._start_watchdog()
        except Exception:
            log.exception("%s: could not retry the file watcher", self.name)

    def _schedule_debounced_run(self) -> None:
        with self._lock:
            # Checked UNDER _lock, which stop() also takes to disarm the
            # timer: a watchdog event delivered while stop() was running used
            # to arm a fresh timer just after stop() had cancelled the old
            # one, firing run_once() on a stopped lane seconds later. Now the
            # two orderings are both safe -- either stop() cancels the timer
            # we armed, or we see its already-set event and arm nothing.
            if self._stop_event.is_set():
                log.debug("%s: not arming a debounced run -- the lane is stopping", self.name)
                return
            if self._debounce_timer is not None:
                self._debounce_timer.cancel()
            self._debounce_timer = threading.Timer(self.watch_debounce_seconds, self._debounced_fire)
            self._debounce_timer.daemon = True
            self._debounce_timer.start()

    def _debounced_fire(self) -> None:
        # A timer that was already counting down when stop() cancelled it can
        # still have fired (Timer.cancel only helps before the deadline), so
        # the check is repeated here and again inside _run_once_locked.
        if self._stop_event.is_set():
            log.debug("%s: debounced run skipped -- the lane is stopping", self.name)
            return
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
            self._express_requeue(ready, batch)
            return
        try:
            # LAST CHECK BEFORE THE SPAWN, under the run lock. Everything
            # between the check at the top of this method and here --
            # partitioning (a stat per path), the lock acquisition, then
            # rclone_available()'s own subprocess and the list-file write
            # inside _express_run -- takes real time, and stop() lands in it
            # routinely during a self-upgrade. _express_spawn re-checks once
            # more while holding the handle lock; this one keeps us from
            # writing a list file and claiming in-flight paths for a run
            # that is about to be refused (KNOWN_BUGS B13).
            if self._express_shutdown.is_set() or self._express_paused.is_set():
                log.debug(
                    "%s: express window dropped -- the lane stopped/paused while "
                    "the batch was being prepared", self.name,
                )
                return
            self._express_run(ready)
        finally:
            self._express_run_lock.release()

    def _express_requeue(self, ready: list[str], batch: dict[str, tuple[int, float]]) -> None:
        """Hand a batch that lost the run lock back to the next window.

        Keeps each path's ORIGINAL first_seen: re-stamping it here restarted
        the EXPRESS_PENDING_MAX_SECONDS give-up clock every window, so a path
        that kept losing this lock was re-stat'd forever instead of being
        handed to the periodic pass. And it respects _express_max_batch like
        every other insertion point -- an unbounded requeue could grow the
        pending map past the cap notify_path_changed() enforces.

        The size is deliberately re-seeded to -1 so the next window re-stats
        and re-proves stability rather than trusting an observation this run
        has already acted on."""
        dropped = 0
        with self._express_lock:
            for index, rel in enumerate(ready):
                if rel in self._express_pending:
                    continue
                if len(self._express_pending) >= self._express_max_batch:
                    dropped = len(ready) - index
                    break
                seen = batch.get(rel)
                first_seen = seen[1] if seen else time.monotonic()
                self._express_pending[rel] = (-1, first_seen)
            self._express_arm_timer_locked()
        if dropped > 0:
            log.debug(
                "%s: express requeue hit the %d-path cap -- %d path(s) left to "
                "the periodic pass", self.name, self._express_max_batch, dropped,
            )

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
        # Same gate as the periodic pass, for the same reason: express builds
        # a --files-from list of paths RELATIVE TO local_root, so against a
        # tree that has gone away every entry names a file that no longer
        # exists. Nothing is lost by standing down -- the paths are still on
        # the drive, and the periodic pass owns them when it returns.
        if not self._local_root_is_present():
            log.debug("%s: express upload skipped -- local root missing "
                      "(drive disconnected?)", self.name)
            return
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
        # Claim these paths BEFORE the child starts: a periodic pass that
        # builds its filter file in the gap between spawn and claim would
        # upload them alongside us, which is the whole thing this prevents.
        # Normalized the way write_files_from_list does, so the strings match
        # what rclone was actually handed.
        claimed = {str(r).replace("\\", "/").strip().strip("/") for r in rels}
        claimed.discard("")
        with self._express_inflight_lock:
            self._express_inflight |= claimed
        try:
            returncode, stderr_text = self._express_spawn(cmd)
        except SpawnCancelled:
            # stop() won the race by a hair. Not a failure and not a counter:
            # the paths are still on disk and the next generation's periodic
            # pass owns them.
            return
        except Exception as exc:
            log.warning("%s: express upload failed to run: %s", self.name, exc)
            self._express_record(0, str(exc))
            return
        finally:
            # Released even on a crash/timeout: a leaked claim would exclude
            # these paths from EVERY future periodic pass, so a failed express
            # run would strand them permanently -- worse than the duplication.
            with self._express_inflight_lock:
                self._express_inflight -= claimed
            # Our own scratch artifact, in our own state dir -- the only
            # thing this feature ever removes. Never user data.
            try:
                os.unlink(list_file)
            except OSError:
                pass

        result = parse_json_log(stderr_text)
        if returncode != 0:
            tail = result.errors[-1] if result.errors else _stderr_for_log(stderr_text)
            # Deliberately NOT STATE_ERROR: express is a bonus path and the
            # periodic pass is still the authority on this lane's health.
            # Painting the lane red from here would make a transient express
            # failure look like a broken lane A.
            log.warning("%s: express upload exited %d: %s", self.name, returncode, tail)
            self._express_record(result.transferred, tail or f"rclone exited {returncode}")
            return
        log.info("%s: express uploaded %d file(s)", self.name, result.transferred)
        # Express files-from paths are already local_root-relative
        # ("Projects/..."), so no subpath prefix.
        self._record_completions(result, None)
        self._express_record(result.transferred, None)

    def _express_record(self, transferred: int, error: Optional[str]) -> None:
        with self._lock:
            self._express_status["runs"] += 1
            self._express_status["files_uploaded"] += transferred
            self._express_status["last_files"] = transferred
            self._express_status["last_error"] = error
            self._express_status["last_run"] = datetime.now(timezone.utc).isoformat()

    def _raise_if_express_stopping(self) -> None:
        """Stand down if _express_stop() has landed. Caller holds
        _express_proc_lock."""
        if self._express_shutdown.is_set():
            log.info(
                "%s: express upload cancelled -- stop() landed before rclone was started",
                self.name,
            )
            raise SpawnCancelled(f"{self.name}: express upload cancelled by stop()")

    def _express_spawn(self, cmd: list[str]) -> tuple[int, str]:
        """Run the express argv. Mirrors run_once()'s two code paths (the
        injected-subprocess_run seam for tests, Popen otherwise) but keeps
        its OWN child handle: stop() must be able to end an express upload
        without touching the periodic run's, and vice versa."""
        if self._legacy_run:
            # Nothing to publish on this seam (subprocess_run blocks and
            # returns a finished process), so the pre-spawn check is the only
            # cancellation point stop() gets.
            with self._express_proc_lock:
                self._raise_if_express_stopping()
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
        # CHECK, SPAWN AND PUBLISH UNDER ONE LOCK -- the fix for the orphaned
        # express child (KNOWN_BUGS B13). _express_stop() sets the shutdown
        # flag and then takes this same lock, so it can no longer slip
        # through the gap where _express_proc was still None because the
        # child was one statement away from existing. The lock is released
        # before the read/wait below, so stop() never waits on a transfer.
        with self._express_proc_lock:
            self._raise_if_express_stopping()
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
            with self._express_proc_lock:
                if self._express_proc is proc:
                    self._express_proc = None
        return returncode, stderr_text
