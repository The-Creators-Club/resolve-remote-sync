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
import unicodedata
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

from .base import (
    STATE_ERROR,
    STATE_IDLE,
    STATE_PAUSED,
    STATE_SYNCING,
    LaneAdapter,
    LaneStatus,
)
from . import lane_guard

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

# YT-3 (resilience sweep 2026-08-28): the ytdl executors download AND convert
# inside the tree, so a half-made file carries a real video extension while
# `_ensure_edit_ready`'s libx264 pass runs (minutes to hours). Lane A is
# `copy --ignore-existing`: the FIRST version of a name to reach the NAS is
# the only one that ever will, so uploading the pre-conversion original makes
# the undecodable copy the whole fleet's permanent one (CR-79 arriving through
# the sync lane). These are `-` rules and MUST come before the `+ *<ext>`
# includes -- rclone filter matching is first-match-wins.
#   *.editready.* / *.original.* -- the conversion's two sides
#   *.temp.*                     -- ffmpeg/yt-dlp scratch output
#   *.fNNN*.*                    -- yt-dlp per-format fragments (.f137.mp4)
#   *.failed                     -- an abandoned attempt, kept for diagnosis
YTDL_WORK_EXCLUDE_RULES = [
    "- *.editready.*",
    "- *.original.*",
    "- *.temp.*",
    "- *.f[0-9][0-9][0-9]*.*",
    "- *.failed",
]

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

# The express path's own tail (SYNC-13). See _express_spawn: its stderr is
# re-parsed for the upload counts, so it needs room for every file in a
# batch, not just the last few hundred lines of a long run.
EXPRESS_STDERR_TAIL_LINES = 4000

# -- the stall watchdog (SYNC-1 / SYS-17, resilience sweep 2026-08-28) ------
#
# CR-91's mechanism. `proc.wait()` had no timeout at all, and rclone's own
# --max-duration is inert against the failure that produced it: a local read
# wedged in the kernel (a Mac's external SSD that stopped answering, a
# subst'ed SMB mapping over a dropped tailnet) never reaches rclone's
# scheduler, so the SOFT cutoff has nothing to cut off. The lane then sat in
# `state=syncing, transferring=1, last_error=NULL` for 2 h 20 m holding
# _run_lock -- and because lane A takes its turn first, lane B never ran and
# the editor downloaded nothing for the whole period.
#
# Two ceilings, and the first one is the one that matters:
#
#   ZERO-PROGRESS: bytes and files moved, NOT wall clock, exactly as CR-91
#   asks -- a genuinely slow 40 GB original over a thin uplink keeps moving
#   the tally and is never killed, however long it takes.
#
#   HARD: a child that has outlived twice its own budget plus five minutes
#   is not doing the work it was given, whatever its stats say.
#
# The poll interval is what turns wait() from unbounded into a loop; it is
# not a timeout on the run.
RCLONE_WAIT_POLL_SECONDS = 30.0
# Floor for the zero-progress window: on a machine with no per-project budget
# (an unmanaged periodic lane) 15 minutes of a lane moving nothing at all is
# already far outside normal.
STALL_ZERO_PROGRESS_MIN_SECONDS = 900.0
STALL_ZERO_PROGRESS_BUDGET_MULTIPLE = 4.0
STALL_HARD_CEILING_MULTIPLE = 2.0
STALL_HARD_CEILING_GRACE_SECONDS = 300.0
# Stands in for a missing per-project budget. Same value as config.py's
# project_rotation_seconds default, deliberately duplicated rather than
# imported: this module depends on nothing above sync/.
DEFAULT_STALL_BUDGET_SECONDS = 600.0
# NEVER IN MEMORY ONLY: a companion that restarts (or self-upgrades) after
# killing a wedged rclone would otherwise erase the only evidence that it
# happened, which is precisely the evidence CR-91 spent a day not having.
LANE_STALL_FILENAME = "lane_stall.json"
# What a killed child's exit code is reported as when it cannot be reaped at
# all -- a process in an uninterruptible kernel wait cannot be killed, and
# waiting on it is the hang we are escaping.
RCLONE_STALL_RETURNCODE = -9


def _stall_budget_seconds(max_duration_seconds: Optional[float]) -> float:
    """The budget the two ceilings are derived from, never zero.

    A hand-edited `project_rotation_seconds = 0` drops --max-duration
    altogether (config.py refuses it, so this is the belt to that braces);
    the watchdog must not be disabled by the same edit."""
    try:
        value = float(max_duration_seconds or 0)
    except (TypeError, ValueError):
        value = 0.0
    return value if value > 0 else DEFAULT_STALL_BUDGET_SECONDS


def zero_progress_limit_seconds(max_duration_seconds: Optional[float]) -> float:
    """How long a run may move NOTHING before it is killed."""
    budget = _stall_budget_seconds(max_duration_seconds)
    return max(
        STALL_ZERO_PROGRESS_BUDGET_MULTIPLE * budget, STALL_ZERO_PROGRESS_MIN_SECONDS
    )


def hard_ceiling_seconds(max_duration_seconds: Optional[float]) -> float:
    """How long a run may last regardless of progress."""
    budget = _stall_budget_seconds(max_duration_seconds)
    return STALL_HARD_CEILING_MULTIPLE * budget + STALL_HARD_CEILING_GRACE_SECONDS


# The dashboard's LaneReportIn cap for the field (api.py). Kept a little
# under it, like MAX_PROJECT_SLUG_CHARS is for its own field.
MAX_PROGRESS_TOKEN_CHARS = 200


def progress_token(
    bytes_done: Optional[int], files_done: int, current_project: Optional[str]
) -> str:
    """The report's `progress_token` for a lane (SYS-1, wave 2 contract).

    Monotonic within a pass and CHEAP: bytes and files the lane has moved,
    plus the project it is moving them for, so the dashboard can red a
    non-terminal state whose token has not changed for 3 rotations. The
    project is in it because a machine rotating through projects with nothing
    to move in any of them is still making progress through its plan."""
    try:
        done = int(bytes_done or 0)
    except (TypeError, ValueError):
        done = 0
    token = f"{done}:{max(0, int(files_done or 0))}:{current_project or ''}"
    # BOUNDED: the dashboard declares `progress_token: str | None =
    # Field(max_length=256)` and pydantic rejects the WHOLE report body on a
    # violation -- which would take lane status, presence and the upgrade
    # advertisement down with it, for a liveness field. Nothing bounds a
    # project rel path (current_project itself is allowed 512), so the sender
    # does. The numeric head is what changes, so the TAIL is what goes.
    return token[:MAX_PROGRESS_TOKEN_CHARS]


def _iso_age_seconds(stamp: Optional[str]) -> Optional[int]:
    """Seconds since an ISO-8601 stamp, or None when there isn't one.

    None for "never ran" and for an unparseable stamp: "could not tell" must
    never render as zero (i.e. as "just now")."""
    if not stamp:
        return None
    try:
        when = datetime.fromisoformat(str(stamp))
    except ValueError:
        return None
    if when.tzinfo is None:
        # Every stamp this module writes carries an offset; a naive one comes
        # from an older state file and is read as UTC (CR-89's lesson).
        when = when.replace(tzinfo=timezone.utc)
    return max(0, int((datetime.now(timezone.utc) - when).total_seconds()))


def write_stall_record(path, record: dict) -> None:
    """Persist the last stall this companion killed. Never raises.

    tmp + os.replace, the same atomic write every other latch in this system
    uses (identity.py): a half-written evidence file must never be what the
    next boot reads."""
    try:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(target.suffix + ".tmp")
        tmp.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, target)
    except Exception:
        log.warning("could not persist the lane stall record to %s", path, exc_info=True)


def read_stall_record(path) -> Optional[dict]:
    """The last persisted stall, or None. Never raises."""
    try:
        raw = Path(path).read_text(encoding="utf-8")
    except OSError:
        return None
    except Exception:
        log.debug("could not read the lane stall record at %s", path, exc_info=True)
        return None
    try:
        record = json.loads(raw)
    except ValueError:
        log.warning("the lane stall record at %s is not JSON -- ignoring it", path)
        return None
    return record if isinstance(record, dict) else None

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

# -- lane A size floor (COMP-GUARD-1, 2026-08-14) --------------------------
#
# Lane A is `copy --ignore-existing`, so the FIRST version of a name to reach
# the NAS is the only one that ever will: a later run sees the destination
# exists and skips it forever. That makes a 0-byte upload permanent, and
# 0-byte finals are a state the fleet actually produces -- a hard kill in the
# middle of the fixer's copy strands the destination at its real name with
# nothing in it (the fixer now sweeps those; this is the second line of
# defence, upstream of the sweep).
#
# Safe because lane A carries NOTHING BUT video: build_filter_rules_up is
# `+ *<ext>` over VIDEO_EXTS and then `- **`, and every one of those is a
# container format with a mandatory header (ftyp/RIFF/EBML/...). There is no
# sidecar, marker or sentinel file on this lane that could legitimately be
# empty -- lane C carries all of those.
#
# "1B", NOT "1". Measured against the bundled rclone 1.74.4: `--min-size 1`
# is parsed as 1 KiB and skipped a real 64-byte file, while `--min-size 1B`
# skips only the empty one. A bare number silently raising the floor a
# thousandfold is exactly the kind of quiet data loss this flag is here to
# prevent.
LANE_A_MIN_SIZE = "1B"

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


def nfc_key(text: str) -> str:
    """A path folded to Unicode NFC for COMPARISON ONLY (SYNC-3, CR-90).

    macOS listdir hands out NFD, the NAS and Windows hand out NFC, so
    `Matej Šimalčík` read off a Mac's disk is a different byte string from the
    same name read off the NAS. Never feed this to anything that opens,
    renames or deletes a file: there the bytes on disk are the truth.
    """
    return unicodedata.normalize("NFC", str(text or ""))


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
    # SYNC-11 (resilience sweep 2026-08-28): each excluded path gets a `/**`
    # companion rule. `- /Sub/Dir` alone is a directory-prune that is easy to
    # get wrong, and a file-moves exclusion CAN name a directory
    # (`file_moves` carries `is_dir`). For a plain file the extra rule matches
    # nothing, and both are `-` rules, so it is free either way.
    for rel in (exclude_paths or []):
        escaped = escape_filter_pattern(rel)
        rules.append(f"- /{escaped}")
        rules.append(f"- /{escaped}/**")
    rules += ["- **/Proxy/**", "- /Proxy/**"]
    rules += YTDL_WORK_EXCLUDE_RULES
    rules += [f"+ *{ext}" for ext in VIDEO_EXTS]
    rules.append("- **")
    return rules


def build_filter_rules_down() -> list[str]:
    """Lane B: Proxy/ dirs at any depth (root included), and nothing else.

    The trash exclude comes FIRST (first-match-wins): the backup dir mirrors
    the source layout, so `.ccsync-trash/<ts>/Sub/Proxy/x.mov` matches
    `**/Proxy/**` and would otherwise be both re-deleted every pass and
    rejected by rclone's backup-dir overlap check.

    IN_PROGRESS_EXCLUDE_RULES come next, and before the includes for the same
    first-match-wins reason: they are what stops the lane pulling a proxy
    Resolve is still writing (see the constant).

    APPLEDOUBLE_EXCLUDE_RULE is ahead of both. It has no ordering quarrel with
    them (all three are `-` rules), but it MUST beat the includes, which
    match every byte under their dirs -- `._p.mov` included.

    `/Youtube/` is deliberately NOT included (2026-08-16), reversing the
    2026-08-13 R12 rule that pulled `+ /Youtube/**` down. That rule existed
    because the NAS-side ytdl worker was the ONLY downloader and no lane
    shipped its originals to editors, so they imported the 540p previews (the
    "Energy Transition" incident). Requester-first downloads (0.7.8 + the
    ffmpeg sidecar) put the original on the requester's disk FIRST and lane A
    carries it up like any other video -- so pulling every editor's YouTube
    originals down to every other editor is pure bandwidth: one editor's first
    pass after upgrading was 58 GB of other people's clips. Owner's call,
    2026-08-16: YouTube originals go UP only, never down. Two consequences,
    both accepted: (1) a clip that fell back to the server path (no local
    capability, or a clip the requester's IP was bot-checked on and the
    server's second-chance sweep fetched) stays NAS-only, and the download
    history's reveal says so instead of "has it synced here yet?"; (2) an
    editor-local original the NAS lacks is now EXCLUDED rather than swept to
    `.ccsync-trash` by this `sync` (KNOWN_BUGS carryover item 22 no longer
    applies to Youtube/). `Youtube/<term>/Proxy/` still comes down through
    `**/Proxy/**` -- previews are small and the generator makes them on the
    base rig. `*.part`/`*.ytdl` stay excluded: harmless without the include,
    and load-bearing the day someone puts a Proxy dir under a download.
    """
    return [
        APPLEDOUBLE_EXCLUDE_RULE,
        TRASH_EXCLUDE_RULE,
        *IN_PROGRESS_EXCLUDE_RULES,
        "- *.part",
        "- *.ytdl",
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


# What _run_bounded reports for a child it had to kill. Non-zero on purpose:
# every caller of _run_capture treats a non-zero code as "the probe failed",
# which is the correct answer for a listing that never finished.
PROBE_TIMEOUT_RETURNCODE = -1


def _run_bounded(
    cmd: list[str],
    timeout: float,
    popen_factory: Optional[Callable[..., Any]] = None,
) -> tuple[Optional[int], str, str]:
    """Run a short-lived rclone command with a REAL bound. (code, out, err).

    `code` is None when the child had to be killed, i.e. nothing it printed
    can be trusted as a complete answer.

    SYNC-12 (resilience sweep 2026-08-28): both helpers below used
    `subprocess.run(timeout=)`, which kills the child on expiry and then
    sits in communicate() waiting for the pipes to close. On Windows an
    rclone that spawned anything inheriting the write handle -- or a child
    stuck in an uninterruptible kernel wait -- leaves that call blocked
    forever, so `list_remote_files`'s documented "ten-minute cap" could be
    infinite. It runs inside _run_lock, on the relocation path, at the exact
    moment the breaker is deciding whether to stop lane B. _end_probe was
    written because the authors already knew this; the knowledge had not
    reached these two.

    The shape is _end_probe's (kill, then a ONE-second wait) plus
    _run_popen's daemon readers and `abandoned` flag: a reader still parked
    on a pipe some grandchild holds open is a thread we walk away from, never
    a lane we block."""
    factory = popen_factory or subprocess.Popen
    proc = factory(
        cmd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        encoding="utf-8",
        errors="replace",
        creationflags=_win_creationflags(),
    )
    abandoned = threading.Event()
    chunks: dict[str, deque] = {"out": deque(), "err": deque()}

    def _read(stream, key: str) -> None:
        # Never let a decode error kill a reader silently: an undrained pipe
        # is how rclone blocks on a full 64 KB buffer and never exits.
        try:
            if stream is None:
                return
            for line in stream:
                if abandoned.is_set():
                    return
                chunks[key].append(line)
        except Exception:
            log.debug("bounded rclone run: %s reader failed", key, exc_info=True)

    threads = [
        threading.Thread(target=_read, args=(proc.stdout, "out"),
                         name="ccsync-rclone-probe-stdout", daemon=True),
        threading.Thread(target=_read, args=(proc.stderr, "err"),
                         name="ccsync-rclone-probe-stderr", daemon=True),
    ]
    for thread in threads:
        thread.start()

    code: Optional[int]
    try:
        code = proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        _end_probe(proc)
        code = None
    except Exception:
        log.warning("bounded rclone run: wait() failed", exc_info=True)
        _end_probe(proc)
        code = None
    for thread in threads:
        thread.join(timeout=STDERR_READER_JOIN_SECONDS if code is not None else 1.0)
    if any(thread.is_alive() for thread in threads):
        abandoned.set()
        log.warning(
            "bounded rclone run: a pipe is still open after the child ended -- "
            "continuing with a partial answer rather than blocking (%s)", cmd[:2],
        )
    try:
        out = "".join(list(chunks["out"]))
        err = "".join(list(chunks["err"]))
    except RuntimeError:
        # An abandoned reader mutated a deque mid-snapshot; a partial answer
        # beats raising into a caller whose next move is a delete decision.
        out, err = "", ""
    return code, out, err


def _run_lsf(cmd: list[str], timeout: float) -> Optional[str]:
    code, out, err = _run_bounded(cmd, timeout)
    if code is None:
        log.warning(
            "rclone lsf did not finish within %.0fs -- killed, treating the listing "
            "as failed: %s", timeout, _stderr_for_log(err),
        )
        return None
    if code != 0:
        log.warning("rclone lsf exited %d: %s", code, _stderr_for_log(err))
        return None
    return out


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

    A READ, and only a read. Retention moved to lane_guard.prune_trash on
    2026-08-17 (COMMERCIAL_READINESS.md item 9); this is what the tray's "how
    much is in trash" line and the report's `sync_guard.trash` field are built
    from. Bounded by `max_entries` so a huge trash tree can't turn a status
    read into a multi-minute walk."""
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


def _run_capture(cmd: list[str], timeout: float) -> tuple[int, str]:
    """Run an rclone command and hand back (returncode, STDERR).

    The sibling of _run_lsf, for the commands whose answer arrives on stderr
    because they carry --use-json-log (lsf answers on stdout). Kept separate
    rather than generalised: an accidental stdout/stderr mix-up in a probe
    that gates a delete is not a bug worth being clever about.

    Bounded through _run_bounded for SYNC-12's reason; a killed child is
    reported as PROBE_TIMEOUT_RETURNCODE, which every caller already reads
    as "the probe failed" (and therefore as "I could not tell", which is
    what makes it refuse the removal)."""
    code, _out, err = _run_bounded(cmd, timeout)
    if code is None:
        log.warning(
            "rclone probe did not finish within %.0fs -- killed: %s",
            timeout, _stderr_for_log(err),
        )
        return PROBE_TIMEOUT_RETURNCODE, err
    return code, err


def list_remote_top(
    rclone_path: str,
    remote: str,
    remote_root: str,
    subpath: Optional[str] = None,
    run_fn: Optional[Callable[[list[str], float], Optional[str]]] = None,
    # Short on purpose: this runs inside _run_lock, i.e. it delays every
    # project's turn on the sequencer's rotation, and a remote that cannot
    # list one directory in a minute is going to fail the pass anyway.
    timeout: float = 60.0,
) -> Optional[list[str]]:
    """Immediate children of the remote side of a lane B pass, or None when
    the listing failed (COMMERCIAL_READINESS.md item 9, 2026-08-17).

    The breaker's pre-flight probe. NOT recursive on purpose: this answers
    "does the remote still look like itself" and has to be affordable on
    every pass, so it costs one directory listing rather than a tree walk.
    Dot-entries are dropped -- `.stfolder`/`.stversions` exist on the NAS
    whether or not a single project does, so counting them would make an
    emptied share look populated.
    """
    if not remote or not remote_root:
        return None
    remote_side = f"{remote}:{_join_remote_path(remote_root, subpath or '')}"
    cmd = [rclone_path, "lsf", remote_side]
    runner = run_fn or _run_lsf
    try:
        output = runner(cmd, timeout)
    except Exception as exc:
        log.debug("remote sanity listing failed for %s: %s", remote_side, exc)
        return None
    if output is None:
        return None
    return [
        name for name in (line.strip().strip("/") for line in output.splitlines())
        if name and not name.startswith(".")
    ]


def list_remote_files(
    rclone_path: str,
    remote: str,
    remote_root: str,
    subpath: Optional[str] = None,
    run_fn: Optional[Callable[[list[str], float], Optional[str]]] = None,
    # Ten minutes, against list_remote_top's sixty seconds, because this one
    # IS the tree walk that one refuses to be. It runs at most once per pass
    # and only when the alternative is stopping the lane, so a slow answer
    # still beats no answer -- but it must not hang the sequencer forever.
    timeout: float = 600.0,
    paths_out: Optional[set] = None,
) -> Optional[dict[str, set[int]]]:
    """`{basename: {size, ...}}` for every file under the remote side of a
    lane B pass, or None when the listing failed.

    The relocation probe's other half (KNOWN_BUGS CR-44, 2026-08-20). Keyed
    by BASENAME rather than path on purpose: the question it answers is
    "this file left the folder rclone was syncing -- is it still on the NAS
    somewhere else?", and the path is the one thing a move changes. Size is
    what keeps that from being a guess: two proxies sharing a basename in
    different folders is ordinary, two sharing a basename AND an exact byte
    count is the same file.

    None (a failed listing) and {} (a genuinely empty remote) are different
    answers and the caller must not confuse them -- an empty remote is the
    case where every local file really is a deletion, which is precisely
    when the breaker must be free to trip.

    `paths_out`, when supplied, is filled with each file's RELATIVE POSIX
    PATH under the scope as well. The basename index above cannot answer
    "is this exact file still where it was", which is the question a file
    the age gate merely filtered out needs answering (comp-lanes-ab-3) --
    and one walk has to serve both, because it is a ten-minute-capped
    recursive listing inside the sequencer's run lock.
    """
    if not remote or not remote_root:
        return None
    remote_side = f"{remote}:{_join_remote_path(remote_root, subpath or '')}"
    # `s` then `p`: the size is numeric and cannot contain the separator, so
    # splitting on the FIRST one leaves the whole (arbitrary, ";"-containing,
    # CJK, fullwidth-punctuation) filename intact as the remainder.
    cmd = [rclone_path, "lsf", "-R", "--files-only", "--format", "sp",
           "--separator", ";", remote_side]
    runner = run_fn or _run_lsf
    try:
        output = runner(cmd, timeout)
    except Exception as exc:
        log.debug("remote relocation listing failed for %s: %s", remote_side, exc)
        return None
    if output is None:
        return None
    found: dict[str, set[int]] = {}
    for line in output.splitlines():
        size_text, sep, path = line.partition(";")
        if not sep:
            continue
        try:
            size = int(size_text.strip())
        except ValueError:
            continue
        rel = path.strip().rstrip("/").lstrip("/")
        name = rel.rsplit("/", 1)[-1]
        if name:
            found.setdefault(name, set()).add(size)
            if paths_out is not None:
                paths_out.add(rel)
    return found


# rclone's per-file line under --dry-run on a `copy`. Measured against the
# bundled 1.74.4: "clip.mov: Skipped copy as --dry-run is set (size 4.2Gi)".
# It is NOT one of the "Copied"/"Moved"/"Deleted" shapes RcloneRunTally
# counts, which is why the pending-upload probe parses its own.
_DRY_RUN_SKIP = "skipped copy"


def scan_pending_uploads(
    rclone_path: str,
    local_root: str,
    remote: str,
    remote_root: str,
    filter_file: Path,
    subpath: Optional[str] = None,
    run_fn: Optional[Callable[[list[str], float], tuple[int, str]]] = None,
    timeout: float = 300.0,
    max_samples: int = 20,
    tuning: Optional["RcloneTuning"] = None,
) -> Optional[dict]:
    """What lane A would upload for `subpath` right now -- a --dry-run of the
    real lane A command (COMMERCIAL_READINESS.md item 9, 2026-08-17).

    The gate on "Remove from this machine": `rmtree` on a project whose
    originals have not reached the NAS is the one destructive action in this
    system with no undo anywhere, and until now the only guard was a sentence
    in a dialog asking the editor to go and check the dashboard themselves.

    Built from build_up_command so the ANSWER MATCHES THE LANE: same filter
    rules, same --min-age/--min-size floors, same --ignore-existing. A file
    the lane would never upload must not block a removal.

    Returns {"count", "samples"} or None when the probe failed -- and None is
    load-bearing: the caller must refuse the removal on it, because "I could
    not tell" is not "there is nothing pending".
    """
    if not remote or not remote_root:
        return None
    cmd = build_up_command(
        rclone_path, local_root, remote, remote_root, filter_file,
        transfers=1, subpath=subpath, tuning=tuning,
    ) + ["--dry-run"]
    runner = run_fn or _run_capture
    try:
        returncode, stderr_text = runner(cmd, timeout)
    except Exception as exc:
        log.warning("pending-upload probe failed for %s: %s", subpath, exc)
        return None
    if returncode != 0:
        log.warning(
            "pending-upload probe exited %s for %s: %s",
            returncode, subpath, _stderr_for_log(stderr_text),
        )
        return None
    count = 0
    samples: list[str] = []
    for line in stderr_text.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if _DRY_RUN_SKIP not in str(record.get("msg", "")).lower():
            continue
        count += 1
        name = str(record.get("object") or "")
        if name and len(samples) < max_samples:
            samples.append(name)
    return {"count": count, "samples": samples}


def scan_size_mismatches(
    rclone_path: str,
    local_root: str,
    remote: str,
    remote_root: str,
    filter_file: Path,
    subpath: Optional[str] = None,
    run_fn: Optional[Callable[[list[str], float], Optional[str]]] = None,
    timeout: float = 600.0,
    max_samples: int = 20,
) -> Optional[dict]:
    """Files lane A has on this machine that the NAS holds AT A DIFFERENT SIZE
    (COMMERCIAL_READINESS.md item 9, 2026-08-17).

    Lane A is `copy --ignore-existing`: the first version of a name to reach
    the NAS is the only one that ever will. Re-export a clip under the same
    name -- which every "fix the audio and render again" does -- and lane A
    skips it forever, silently, with the editor watching a green lane. That
    is the one shape of data loss on lane A, and nothing anywhere reported it.

    `rclone check --one-way --size-only --differ -` is exactly this question:
    --one-way ignores what the NAS has and we don't, --size-only compares the
    thing that actually differs (a re-export is a different length; the hashes
    would cost a full re-read of every original over SFTP), and --differ -
    puts the answers on stdout. Same filter file as the lane, so a file the
    lane would never carry cannot appear here.

    Returns {"count", "samples"} or None when the check could not run.
    """
    if not remote or not remote_root:
        return None
    validate_filter_file(filter_file)
    local_sub = _local_subpath(subpath)
    local_side = str(Path(local_root) / local_sub) if local_sub else str(local_root)
    remote_side = f"{remote}:{_join_remote_path(remote_root, subpath or '')}"
    cmd = [
        rclone_path, "check", local_side, remote_side,
        "--filter-from", str(filter_file),
        "--ignore-case",
        "--size-only",
        "--one-way",
        "--differ", "-",
        *_transport_flags(),
    ]
    # _run_check, NOT _run_lsf: `rclone check` exits 1 whenever it FINDS a
    # difference, and _run_lsf's returncode guard would swallow exactly the
    # answer this function exists to produce.
    runner = run_fn or _run_check
    try:
        output = runner(cmd, timeout)
    except Exception as exc:
        log.debug("size-mismatch check failed for %s: %s", subpath, exc)
        return None
    if output is None:
        return None
    names = [line.strip() for line in output.splitlines() if line.strip()]
    return {"count": len(names), "samples": names[:max_samples]}


def _run_check(cmd: list[str], timeout: float) -> Optional[str]:
    """`rclone check`'s stdout, tolerating its non-zero "found differences"
    exit. Measured against the bundled 1.74.4: exit 1 with `--differ -` and
    real differences on stdout, exit 0 when everything matches. Only a
    missing binary / unreachable remote produces empty stdout AND non-zero,
    which reads as {"count": 0} -- acceptable for an advisory counter, and
    the reason this is not used to gate anything destructive."""
    proc = subprocess.run(
        cmd,
        capture_output=True,
        timeout=timeout,
        encoding="utf-8",
        errors="replace",
        creationflags=_win_creationflags(),
    )
    if proc.returncode not in (0, 1):
        log.warning(
            "rclone check exited %d: %s", proc.returncode, _stderr_for_log(proc.stderr)
        )
        return None
    return proc.stdout


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
        # COMP-GUARD-1 (2026-08-14): --ignore-existing above is what makes an
        # empty upload PERMANENT -- the first version of a name to land on the
        # NAS is the only one that will, so a 0-byte final stranded by a hard
        # kill mid-copy would be the fleet's canonical copy of that clip
        # forever. See LANE_A_MIN_SIZE for why 1B and why nothing legitimate
        # on this lane can be empty.
        "--min-size", LANE_A_MIN_SIZE,
        "--transfers", str(transfers),
        *tuning.flags(DIRECTION_UP),
        *_transport_flags(),
        *_max_duration_flags(max_duration_seconds),
        "--use-json-log",
        "--verbose",  # INFO-level per-file log lines — parse_json_log() needs these
    ]
    return _append_stats_flags(cmd, stats_interval)


def _basename_rule_regex(rule: str) -> "re.Pattern[str]":
    """One rclone basename filter rule (`- *.f[0-9][0-9][0-9]*.*`) compiled to
    a case-insensitive regex over a basename.

    Derived from the rule STRINGS rather than hand-written, so
    path_matches_lane_a_filter cannot drift from the rule list the periodic
    pass uses -- which is exactly how YT-3's five rules ended up enforced on
    one lane A door and not the other (bug-hunt-2026-09-03 comp-sync-1).
    Only the glob subset those rules use is translated: `*` (any run of
    non-separator characters, possibly empty), `?`, and a `[...]` class.
    None of them contains a `/`, so rclone matches them against the basename.
    """
    body = rule[2:] if rule.startswith(("- ", "+ ")) else rule
    out = []
    i = 0
    while i < len(body):
        ch = body[i]
        if ch == "*":
            out.append(r"[^/\\]*")
        elif ch == "?":
            out.append(r"[^/\\]")
        elif ch == "[":
            end = body.find("]", i + 1)
            if end == -1:
                out.append(re.escape(ch))
            else:
                out.append("[" + body[i + 1:end].replace("\\", "\\\\") + "]")
                i = end
        else:
            out.append(re.escape(ch))
        i += 1
    return re.compile("".join(out) + r"\Z", re.IGNORECASE)


# Compiled once: this runs on every watchdog event, thousands a minute during
# a card ingest.
YTDL_WORK_EXCLUDE_RES = [_basename_rule_regex(rule) for rule in YTDL_WORK_EXCLUDE_RULES]


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

    The same is true of YT-3's ytdl work files, which is why they are here
    too (bug-hunt-2026-09-03 comp-sync-1): `Interview.original.mp4` and
    `Interview.f137.mp4` sit unchanged on disk for the whole conversion, so
    they clear the express size-stability and min-age gates easily, and lane
    A's --ignore-existing makes that first landing the fleet's permanent copy.
    """
    if not path:
        return False
    if os.path.splitext(path)[1].lower() not in VIDEO_EXTS:
        return False
    parts = [seg for chunk in str(path).split("/") for seg in chunk.split("\\")]
    if parts and parts[-1].startswith("._"):
        return False
    if parts and any(rx.match(parts[-1]) for rx in YTDL_WORK_EXCLUDE_RES):
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
    max_duration_seconds: float | None = None,
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
        # SYNC-13 (resilience sweep 2026-08-28): express had NO duration
        # bound at all, and a wedged express run holds _express_run_lock for
        # the life of the process -- every later window loses the lock,
        # requeues, and finally gives up to the periodic pass, so express
        # dies permanently and the only symptom is that new clips take a
        # whole rotation to reach the NAS instead of ~10 s. NOT a filter flag
        # (--files-from-raw refuses those, see below): --max-duration is a
        # copy flag, verified against the bundled 1.74.4.
        *_max_duration_flags(max_duration_seconds),
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
# ...and the record rclone emits immediately BEFORE it, for the same object.
# Measured against the bundled 1.74.4 with --use-json-log (comp-lanes-ab-4).
_SERVER_SIDE_MOVE = "Moved (server-side)"


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
        elif _SERVER_SIDE_MOVE in msg:
            # --backup-dir emits TWO records per file it moves aside:
            # "Moved (server-side)" and then "Moved into backup dir", both
            # naming the same object. The first matched the per-file rule
            # below, so every trashed proxy was counted as a COMPLETED
            # DOWNLOAD and landed in the dashboard's transfer history as a
            # file that had just arrived, while "transferred N file(s)"
            # counted it twice (comp-lanes-ab-4, 2026-08-21 -- the SYNC-10
            # symptom through the record SYNC-10's fix did not know about).
            # The "into backup dir" twin is what carries the meaning, so this
            # one is worth nothing at all: lane B is the only lane that can
            # emit it (lane A is `copy`).
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


# -- project directories: where they were last seen, and what else is there --
#
# UX-3 / SYNC-10 (resilience sweep 2026-08-28). Two questions nothing in this
# system could answer before:
#   * lane A found no source directory: has it NEVER been here (first run,
#     lane C has not delivered it yet), or was it here last pass? The first is
#     ordinary; the second means an editor renamed or moved the folder in
#     Explorer and everything they put in it from that moment on is invisible
#     to the fleet, reported as IDLE.
#   * is there a project directory on this machine that is in no selection at
#     all? A repath onto an occupied target (repath.py's "re-pointing the
#     folder anyway"), a half-finished move, a drag in Explorer -- all leave a
#     tree no lane will ever touch again, counted as this machine's presence.
# Both are answered from the .ccsync-project marker, which is the only thing
# about a project that survives being renamed.
PROJECT_DIRS_FILENAME = "project_dirs.json"
# The walk is bounded rather than trusted: `Projects/` on a base rig is the
# whole NAS share, and an unbounded os.walk of it on the orphan cadence would
# be a stat storm over SMB. A marker directory is never descended into (a
# project holds no projects), so the cap only bites on a tree with tens of
# thousands of non-project folders.
MAX_PROJECT_SCAN_DIRS = 20000
# Per stray directory, so one enormous orphan cannot make the scan itself the
# problem it is reporting.
MAX_STRAY_SIZE_FILES = 20000
# The wire contract's cap (WAVE4_CONTRACT: `stray_projects.paths` <= 20,
# `moved_project_dirs` <= 20).
MAX_REPORTED_PROJECT_DIRS = 20


def scan_project_markers(local_root: Any) -> Optional[dict[str, str]]:
    """Every `.ccsync-project` under `<local_root>/Projects`, as slug -> dir.

    None means "could not look" (no Projects directory, an unreadable tree) --
    which callers MUST NOT read as "there are none": a scan that cannot run is
    not evidence that nothing moved. Bounded by MAX_PROJECT_SCAN_DIRS and
    never raises.

    On a duplicate slug (a copied project directory, which does happen) the
    FIRST one found wins and the rest are logged: this map is used to offer a
    move, and guessing between two candidates is exactly the guess a marker
    exists to avoid.
    """
    root = Path(local_root) / "Projects"
    try:
        if not root.is_dir():
            return None
    except OSError:
        return None
    found: dict[str, str] = {}
    visited = 0
    try:
        for dirpath, dirnames, _files in os.walk(str(root)):
            visited += 1
            if visited > MAX_PROJECT_SCAN_DIRS:
                log.warning(
                    "project marker scan stopped after %d directories under %s -- "
                    "the answer is incomplete", MAX_PROJECT_SCAN_DIRS, root,
                )
                break
            slug = read_project_slug(dirpath)
            if not slug:
                continue
            # A project directory holds no projects: prune the descent.
            dirnames[:] = []
            if slug in found:
                log.warning(
                    "two directories carry the project marker %s (%s and %s) -- "
                    "keeping the first", slug, found[slug], dirpath,
                )
                continue
            found[slug] = dirpath
    except OSError:
        log.debug("project marker scan failed under %s", root, exc_info=True)
        return found or None
    return found


def _dir_size_bytes(directory: Any, max_files: int = MAX_STRAY_SIZE_FILES) -> int:
    """Bytes under `directory`, bounded and never raising. 0 when unreadable.

    Deliberately an UNDER-count when the cap bites: this number is shown as
    "how much disk this is costing you", and a bounded truth beats an
    unbounded walk of a directory that is already the anomaly."""
    total = 0
    seen = 0
    try:
        for _dirpath, _dirnames, filenames in os.walk(str(directory)):
            for name in filenames:
                seen += 1
                if seen > max_files:
                    return total
                try:
                    total += os.path.getsize(os.path.join(_dirpath, name))
                except OSError:
                    continue
    except OSError:
        return total
    return total


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
        breaker: Optional["lane_guard.LaneBBreaker"] = None,
        disk_floor: Optional["lane_guard.DiskFloorLatch"] = None,
        remote_list_fn: Optional[Callable[[list[str], float], Optional[str]]] = None,
        extra_excludes_fn: Optional[Callable[[Optional[str]], list[str]]] = None,
    ) -> None:
        assert direction in (DIRECTION_UP, DIRECTION_DOWN)
        self.direction = direction
        # Lane A only: run-relative paths the server has MOVED AWAY from
        # (file_moves.FileMoveLedger.recent_excludes). Without this the copy
        # still sitting at the old path re-uploads itself on the next pass,
        # undoing the admin's move (docs/FILE_MOVES.md, 2026-08-27).
        self.extra_excludes_fn = extra_excludes_fn
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
        self._project_dirs_file = self._state_dir / PROJECT_DIRS_FILENAME

        # -- lane B circuit breaker (COMMERCIAL_READINESS.md item 9) ------
        # Constructed HERE, not injected-or-nothing, so a lane B built by any
        # caller (the app, a test, consolidate) carries the breaker: the one
        # verb in this system that removes local files must never be able to
        # run unguarded because a call site forgot an argument. app.py passes
        # its own instance so the tray and the report read the same object.
        if direction == DIRECTION_DOWN:
            self.breaker = breaker or lane_guard.LaneBBreaker(
                self._state_dir / lane_guard.BREAKER_STATE_FILENAME, cfg,
            )
        else:
            self.breaker = breaker
        # -- lane B's free-space floor (SYS-5 / SYNC-7, sweep 2026-08-28) --
        # Constructed here for the same reason the breaker is: the one lane
        # that fills an editor's disk must never run unguarded because a call
        # site forgot an argument. app.py passes its own instance so the tray,
        # the report and the lane read one object.
        if direction == DIRECTION_DOWN:
            self.disk_floor = disk_floor or lane_guard.DiskFloorLatch(
                self._state_dir / lane_guard.DISK_FLOOR_STATE_FILENAME, cfg,
            )
        else:
            self.disk_floor = disk_floor
        # Injectable so a test can drive the floor without a full disk. Not a
        # constructor argument by accident: `free_bytes_at` is the seam every
        # other free-space check in the tree uses.
        self._free_bytes_fn: Callable[[Any], Optional[int]] = lane_guard.free_bytes_at
        # Injectable for the tests, exactly like subprocess_run: the probe
        # spawns a real `rclone lsf` otherwise.
        self._remote_list_fn = remote_list_fn
        self._trash_prune_interval = _cfg_int(
            cfg, "trash_prune_interval_seconds",
            int(lane_guard.DEFAULT_TRASH_PRUNE_INTERVAL_SECONDS),
        )
        self._trash_max_age_days = _cfg_int(
            cfg, "trash_max_age_days", int(lane_guard.DEFAULT_TRASH_MAX_AGE_DAYS))
        self._trash_max_bytes = _cfg_int(
            cfg, "trash_max_bytes", lane_guard.DEFAULT_TRASH_MAX_BYTES)
        self._last_trash_prune_at: Optional[float] = None
        self._trash_summary: Optional[dict] = None
        # Lane A only: same-name-different-size files `copy --ignore-existing`
        # will never upload (see scan_size_mismatches). Refreshed on the
        # orphan-scan cadence, reported and surfaced -- never acted on.
        self._size_mismatches: Optional[dict] = None
        # UX-3: project dirs this lane has actually run against, so a source
        # that vanishes is told apart from one that was never here. On disk
        # (state_dir/project_dirs.json), not in memory: the restart that
        # follows an editor's rename would otherwise forget the whole point.
        self._moved_project_dirs: list[dict] = []
        # SYNC-10: project dirs in no selection at all. None until the first
        # scan -- an absent section is "we have not looked", never "there are
        # none".
        self._stray_projects: Optional[dict] = None

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
        # What the periodic run in flight is copying: its subpath, "" for the
        # whole tree, None when no child is running. Read by the express path
        # so it can defer paths that run already covers (SYNC-3, 2026-08-14 --
        # see periodic_inflight_subpath). Its OWN lock, for the same reason
        # _express_inflight has one: the express thread reads it while the
        # periodic thread writes it, and neither may queue behind a run lock.
        self._periodic_scope: Optional[str] = None
        self._periodic_scope_lock = threading.Lock()
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

        # -- the stall watchdog (SYNC-1 / SYS-17, CR-91) ------------------
        # Attributes, not constructor arguments: every caller of this class
        # (app.py, consolidate, the tests) would otherwise have to learn
        # three knobs that only a test ever sets. The clock is injectable for
        # exactly that reason -- a test must be able to drive four hours of
        # a wedged mount without sleeping for them.
        self._monotonic: Callable[[], float] = time.monotonic
        self._wait_poll_seconds = RCLONE_WAIT_POLL_SECONDS
        # Shared by both lanes on purpose: the report has ONE `stalled` slot,
        # and "the last stall this machine killed" is the question it answers.
        self._stall_file = self._state_dir / LANE_STALL_FILENAME
        self._last_stall: Optional[dict] = None
        self._pending_stall_detail: Optional[str] = None
        # SYNC-13: the express command had no --max-duration at all. The
        # rotation budget is the sanctioned answer -- an express batch that
        # has not finished in the time a whole project pass is allowed is not
        # the ~10 s path the feature exists to be.
        self._express_max_duration = float(max(
            60, _cfg_int(cfg, "project_rotation_seconds",
                         int(DEFAULT_STALL_BUDGET_SECONDS))))
        # Files the last run actually moved (transferred + trashed). The
        # sequencer reads it to tell a pass that did work from one that found
        # nothing to do, which is what its idle backoff keys on
        # (ops-efficiency-2, 2026-08-21).
        self._last_run_moved = 0
        # Has `remote_root` itself been confirmed to hold the marker dirs
        # this process? In managed mode every pass names a project subpath,
        # so the breaker's root probe never ran at all (sync-safety-5,
        # 2026-08-21). Once per process: it is one `lsf` of one directory,
        # and a root that answered correctly does not become somebody's home
        # directory later.
        self._remote_root_checked = False
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

    def periodic_inflight_subpath(self) -> Optional[str]:
        """Scope of the periodic run that is copying RIGHT NOW ("" = the whole
        tree), or None when no child of this lane is running.

        SYNC-3 (2026-08-14): _build_command's express exclusion only closes
        one of the two orderings -- rclone parses --filter-from once, at
        startup, so a path express claims AFTER the periodic child started
        cannot be excluded from that run at all. And that is the COMMON
        ordering: a periodic pass lasts up to project_rotation_seconds (600 s
        by default) while an express window is watch_debounce_seconds (10 s)
        plus the stability/min-age gate, so express almost always starts
        during a periodic run rather than before it. This is the other half of
        the exclusion: express asks what is in flight and defers anything that
        run already covers (_express_partition). The symptom it removes is the
        one measured on an editor's machine 2026-08-02 -- the same .mov
        climbing on two concurrent connections, splitting a saturated uplink.
        """
        with self._periodic_scope_lock:
            return self._periodic_scope

    def _set_periodic_scope(self, subpath: Optional[str]) -> None:
        with self._periodic_scope_lock:
            self._periodic_scope = subpath

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
        <rel>/<the file's original relative path>`.

        Retention CHANGED 2026-08-17 (COMMERCIAL_READINESS.md item 9). It was
        "nothing ever prunes it -- deleting the recovery copy would defeat its
        whole purpose" (AUDIT_2 C-7), which was right while the trash was the
        only thing between a mis-sync and permanent loss. With the circuit
        breaker in front of it the trash is a 14-day undo window, not an
        archive, and an unbounded one filled editor SSDs -- so
        lane_guard.prune_trash now ages it out (and never runs at all while
        the breaker is tripped)."""
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
            if self.extra_excludes_fn is not None:
                try:
                    moved_away = [
                        str(rel).replace("\\", "/").strip("/")
                        for rel in (self.extra_excludes_fn(subpath) or [])
                    ]
                except Exception:
                    log.exception("%s: extra_excludes_fn failed -- excluding nothing", self.name)
                    moved_away = []
                moved_away = [rel for rel in moved_away if rel and rel not in excludes]
                if moved_away:
                    log.info(
                        "%s: keeping %d path(s) the server moved away from out of this run",
                        self.name, len(moved_away),
                    )
                    excludes += moved_away
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

    def arm(self) -> None:
        """Clear the stop latch so an externally-driven run_once() can spawn
        again. Idempotent, and a no-op on a lane that was never stopped.

        SYNC-1 (2026-08-14): nothing re-armed LANE B in managed mode.
        _stop_lanes() stops it (RcloneLane.stop() is the only path to
        _kill_running_process), but the managed _start_lanes() starts lane C,
        the sequencer and lane A's watchdog only -- lane B is driven purely by
        sequencer.run_once(subpath). So after one sign-out/sign-in, or a token
        expiry followed by a re-sign-in, lane B's _stop_event stayed set for
        the life of the process: every later run_once() returned the STALE
        LaneStatus at the guard in _run_once_locked without spawning rclone,
        nothing logged above DEBUG, and the fleet grid kept showing the lane
        idle-and-green while no proxy was ever downloaded again. The sequencer
        calls this for both lanes it drives (see Sequencer.start).

        Same rule as start_watchdog_only's event reset, for the same reason: a
        LIVE periodic generation owns the event it was handed, and clearing
        that in place is exactly what resurrected stale threads before
        per-generation events existed (AUDIT_2 L-2). Install a fresh one
        instead, and only when no such generation is running.
        """
        if self._periodic_thread is not None and self._periodic_thread.is_alive():
            return
        if not self._stop_event.is_set():
            return
        log.info("%s: re-armed (a previous stop() had latched it off)", self.name)
        self._stop_event = threading.Event()

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
        self._refresh_size_mismatches(subpath)
        # SYNC-10 (sweep 2026-08-28): local-only, so it costs no NAS listing
        # at all -- but it belongs on this cadence because it is the same kind
        # of answer (a leftover nobody is going to delete) and a per-pass tree
        # walk would not be free.
        try:
            self._refresh_stray_projects()
        except Exception:
            log.exception("%s: stray project scan failed", self.name)
        return report

    def _refresh_size_mismatches(self, subpath: Optional[str] = None) -> Optional[dict]:
        """The "skipped, exists" counter (COMMERCIAL_READINESS.md item 9,
        2026-08-17), on the orphan scan's cadence because it costs the same
        kind of remote listing.

        `copy --ignore-existing` never re-uploads a name the NAS already
        has, so a re-exported clip is silently stranded on the editor's
        machine forever with the lane showing green. Reported, never acted
        on: overwriting the NAS copy from here would be lane A growing a
        delete/replace path, which is exactly what this system does not do.
        Never raises."""
        try:
            report = scan_size_mismatches(
                self.rclone_path, self.local_root, self.remote, self.remote_root,
                self._ensure_filter_file(), subpath,
            )
        except Exception:
            log.debug("%s: size-mismatch scan failed", self.name, exc_info=True)
            return None
        if report is None:
            return None
        report = {**report, "subpath": subpath,
                  "checked_at": datetime.now(timezone.utc).isoformat()}
        if report.get("count"):
            log.warning(
                "%s: %d file(s) under %s exist on the NAS AT A DIFFERENT SIZE -- "
                "lane A is `copy --ignore-existing`, so these will never be "
                "re-uploaded (first sample: %s). Rename the local file, or have an "
                "admin remove the NAS copy, if the local one is the good one.",
                self.name, report["count"], subpath or "the tree",
                (report.get("samples") or ["?"])[0],
            )
        with self._lock:
            self._size_mismatches = report
        return report

    def size_mismatch_report(self) -> Optional[dict]:
        """Last "same name, different size" scan, or None. See
        _refresh_size_mismatches."""
        with self._lock:
            return dict(self._size_mismatches) if self._size_mismatches else None

    def pending_uploads(self, subpath: Optional[str] = None) -> Optional[dict]:
        """What lane A still owes the NAS for `subpath` -- the gate on
        "Remove from this machine" (item 9). None means "could not tell",
        which the caller MUST treat as "do not delete". Never raises."""
        if self.direction != DIRECTION_UP:
            return None
        try:
            return scan_pending_uploads(
                self.rclone_path, self.local_root, self.remote, self.remote_root,
                self._ensure_filter_file(), subpath, tuning=self.tuning,
            )
        except Exception:
            log.exception("%s: pending-upload probe failed", self.name)
            return None

    def orphan_report(self) -> Optional[dict]:
        """Last refresh_orphan_report() result, or None if never run.

        Public so the reporter payload (owned elsewhere) and the tray can
        surface it without re-listing the NAS."""
        with self._lock:
            return dict(self._orphans) if self._orphans else None

    # -- project directories (UX-3 / SYNC-10, sweep 2026-08-28) -----------
    def _read_project_dirs(self) -> dict[str, dict]:
        """The persisted "this project dir was here" map. {} when unreadable.

        Never raises: a state file we cannot read costs UX-3's distinction
        (every absence reads as "never seen"), which is exactly the behaviour
        that existed before it."""
        try:
            raw = json.loads(self._project_dirs_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        seen = raw.get("seen") if isinstance(raw, dict) else None
        if not isinstance(seen, dict):
            return {}
        return {str(k): v for k, v in seen.items() if isinstance(v, dict)}

    def _write_project_dirs(self, seen: dict[str, dict]) -> None:
        """tmp + os.replace, the same atomic write every other latch here
        uses. Never raises."""
        payload = {"version": 1, "seen": seen,
                   "updated_at": datetime.now(timezone.utc).isoformat()}
        tmp = self._project_dirs_file.with_name(
            f"{self._project_dirs_file.name}.{os.getpid()}.tmp")
        try:
            self._project_dirs_file.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            os.replace(str(tmp), str(self._project_dirs_file))
        except OSError:
            log.debug("%s: could not write %s", self.name, self._project_dirs_file,
                      exc_info=True)
            try:
                tmp.unlink()
            except OSError:
                pass

    def _project_dir_key(self, subpath: Optional[str]) -> str:
        return str(subpath or "").strip().replace("\\", "/").strip("/")

    def _note_project_dir_seen(self, subpath: Optional[str]) -> None:
        """Record that this project's directory was here for this pass.

        Also clears any moved-project entry for it: an editor who put the
        folder back (by hand or with the tray's button) must not keep an
        alarm that has stopped being true."""
        key = self._project_dir_key(subpath)
        if not key:
            return
        try:
            seen = self._read_project_dirs()
            slug = self._project_slug_for_subpath(key) or ""
            entry = dict(seen.get(key) or {})
            entry["last_seen_at"] = datetime.now(timezone.utc).isoformat()
            entry["path"] = str(Path(self.local_root) / Path(*key.split("/")))
            if slug:
                entry["slug"] = slug
            seen[key] = entry
            self._write_project_dirs(seen)
        except Exception:
            log.debug("%s: could not record the project dir for %s", self.name, key,
                      exc_info=True)
        with self._lock:
            self._moved_project_dirs = [
                m for m in self._moved_project_dirs
                if self._project_dir_key(m.get("subpath")) != key
            ]

    def _project_dir_absent(self, subpath: str) -> LaneStatus:
        """Lane A has no source directory: IDLE if it was never here, ERROR
        if it was here last pass and has gone (UX-3).

        The old string ("project dir not yet local") reads like ordinary
        first-run state on the tray line and the fleet chip, which is why an
        editor who renamed a folder in Explorer saw nothing wrong while
        everything they filed in it stopped reaching the fleet."""
        key = self._project_dir_key(subpath)
        record = self._read_project_dirs().get(key) or {}
        if not record.get("last_seen_at"):
            with self._lock:
                self._status.state = STATE_IDLE
                self._status.detail = f"project dir not yet local: {subpath}"
            return self.status()

        label = key.split("/")[-1] or key
        slug = str(record.get("slug") or "")
        expected = str(Path(self.local_root) / Path(*key.split("/")))
        found = self._find_moved_project_dir(slug) if slug else None
        sentence = (f"Your project folder for {label} is not where CCSync expects "
                    "it. Did you rename or move it?")
        if found:
            sentence += f" It looks like it is at {found} now."
        log.error("%s: %s (expected %s)", self.name, sentence, expected)
        with self._lock:
            self._status.state = STATE_ERROR
            self._status.detail = sentence
            self._status.last_error = sentence
            entry = {"slug": slug or None, "subpath": key,
                     "expected": expected, "found": found}
            self._moved_project_dirs = (
                [m for m in self._moved_project_dirs
                 if self._project_dir_key(m.get("subpath")) != key]
                + [entry]
            )[-MAX_REPORTED_PROJECT_DIRS:]
        return self.status()

    def _find_moved_project_dir(self, slug: str) -> Optional[str]:
        """Where the marker for `slug` is now, or None.

        The self-heal half of UX-3: the marker travels with the directory, so
        a folder an editor renamed or dragged is still identifiable. None
        covers "the scan could not run" as well as "it is not on this
        machine" -- both mean the same thing to the caller (offer nothing),
        and neither is ever acted on automatically."""
        if not slug:
            return None
        try:
            markers = scan_project_markers(self.local_root)
        except Exception:
            log.debug("%s: marker scan failed", self.name, exc_info=True)
            return None
        if not markers:
            return None
        return markers.get(slug)

    def moved_project_dirs(self) -> list[dict]:
        """`sync_guard.moved_project_dirs`: the project dirs that were here
        and are not (UX-3). Empty list means none, which is how "every
        selected project is where it should be" is spelled."""
        with self._lock:
            return [dict(m) for m in self._moved_project_dirs]

    def stray_projects(self) -> Optional[dict]:
        """Last stray-project-dir scan (SYNC-10), or None if never run."""
        with self._lock:
            return dict(self._stray_projects) if self._stray_projects else None

    def _refresh_stray_projects(self) -> Optional[dict]:
        """Project directories on this machine that are in NO selection.

        Report-only, on the orphan scan's cadence and with the orphan scan's
        posture: nothing here removes a byte. A repath onto an occupied
        target leaves the old tree in place deliberately (repath.py:283), and
        that tree is then in no lane's scope for ever -- lane B never syncs
        it, lane A never uploads it, and the manifest still counts its files
        as this machine's.

        Returns None for "could not tell", which is NOT "there are none": no
        selection source wired, or a selection that is empty because the
        dashboard has not answered yet, both mean the whole tree would look
        stray. Never raises."""
        if self.known_rels_fn is None:
            return None
        try:
            rels = [str(r) for r in (self.known_rels_fn() or []) if r]
        except Exception:
            log.debug("%s: stray scan could not read the selection", self.name,
                      exc_info=True)
            return None
        if not rels:
            # Empty is ambiguous (before the first fetch, and whenever the
            # dashboard is unreachable, the sequencer answers []), and the
            # ambiguous reading here would name every project on the machine.
            return None
        markers = scan_project_markers(self.local_root)
        if markers is None:
            return None
        expected = {
            os.path.normcase(os.path.normpath(
                str(Path(self.local_root) / "Projects" / Path(*rel.strip("/").split("/")))))
            for rel in rels
        }
        strays: list[dict] = []
        total = 0
        for slug, directory in sorted(markers.items(), key=lambda kv: kv[1]):
            if os.path.normcase(os.path.normpath(directory)) in expected:
                continue
            size = _dir_size_bytes(directory)
            total += size
            strays.append({"slug": slug, "path": directory, "bytes": size})
        report = {
            "count": len(strays),
            "bytes": total,
            "paths": [s["path"] for s in strays[:MAX_REPORTED_PROJECT_DIRS]],
            "slugs": [s["slug"] for s in strays[:MAX_REPORTED_PROJECT_DIRS]],
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }
        if strays:
            log.warning(
                "%s: %d project folder(s) on this machine are in no sync plan "
                "(%.1f GB) -- no lane touches them and nothing here deletes them; "
                "first: %s", self.name, len(strays), total / 1e9, strays[0]["path"],
            )
        with self._lock:
            self._stray_projects = report
        return report

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
        # Cleared here rather than only set at the end, so an early return
        # (breaker, stopped lane, missing root) reads as "this pass moved
        # nothing" instead of repeating the last real pass's count.
        self._last_run_moved = 0
        # Same reasoning for the stall sentence: a pass that ended down one
        # of the early-return paths must not hand its predecessor's stall to
        # the NEXT pass as that pass's error.
        self._take_pending_stall()
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

        # The circuit breaker, ahead of rclone_available() and the command
        # build so a tripped lane B costs nothing at all per pass
        # (COMMERCIAL_READINESS.md item 9, 2026-08-17). PAUSED, not ERROR:
        # the lane is not broken, it has been stopped on purpose, and the
        # sequencer must keep rotating lanes A and C through this machine's
        # projects exactly as before.
        if self.breaker is not None and self.breaker.tripped:
            return self._breaker_stand_down()

        # ...and the free-space floor, on the same terms and in the same
        # place (SYS-5 / SYNC-7, resilience sweep 2026-08-28). Ahead of the
        # remote listing below: a full disk is knowable without touching the
        # NAS at all, and a parked lane must cost nothing per pass.
        disk_reason = self._check_disk_floor()
        if disk_reason:
            return self._disk_stand_down(disk_reason)

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
                return self._project_dir_absent(subpath)
            # UX-3: seen, with today's date and today's marker slug. Cheap
            # (one small JSON rewrite per project per pass) and it is the only
            # record that separates "gone" from "never arrived".
            self._note_project_dir_seen(subpath)

        # PRE-FLIGHT, and it is the only guard that fires before a byte moves:
        # `--max-delete` bounds one pass, this refuses to start the pass at all
        # against a remote that does not look like the tree (a wrong
        # remote_root, an empty/half-mounted share). COMMERCIAL_READINESS.md
        # item 9, 2026-08-17.
        if self.direction == DIRECTION_DOWN and self.breaker is not None:
            scope = str(subpath or "").replace("\\", "/").strip("/")
            entries = list_remote_top(
                self.rclone_path, self.remote, self.remote_root, subpath,
                run_fn=self._remote_list_fn,
            )
            if self.breaker.check_remote(scope, entries) is not None:
                return self._breaker_stand_down()
            # Counted BEFORE the run: it is the denominator of the breaker's
            # fraction rule, and after the pass the files it measures may be
            # the ones that were trashed.
            local_proxies = lane_guard.count_local_proxies(self.local_root, subpath)
        else:
            local_proxies = 0

        with self._lock:
            self._status.state = STATE_SYNCING
            self._status.transferring = 1
            self._status.current_project = subpath
            self._status.bytes_done = None
            self._status.bytes_total = None
            self._status.speed_bps = None
            self._status.eta_seconds = None
            self._status.transfers = []
            # SYS-1: stamped at the START of the pass, not only on the first
            # --stats tick, because the run that has moved nothing at all is
            # the one the dashboard has to be able to red. A token that
            # exists and never changes is evidence; an absent one is not.
            self._status.progress_token = progress_token(0, 0, subpath)

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

        # Published for as long as this run's child lives: the express path
        # reads it and defers anything this run already covers, because
        # rclone read our --filter-from at spawn and can no longer be told
        # about an express claim made after that (SYNC-3, 2026-08-14 -- see
        # periodic_inflight_subpath). Cleared in the finally, including on
        # every early return below, or a crashed run would exclude its
        # subpath from express forever.
        self._set_periodic_scope(str(subpath or "").replace("\\", "/").strip("/"))
        try:
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
                    returncode, stderr_text, result = self._run_popen(
                        cmd, max_duration_seconds)
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
        finally:
            self._set_periodic_scope(None)

        self._record_completions(result, subpath)
        # What this pass actually moved, for the sequencer's idle backoff
        # (ops-efficiency-2, 2026-08-21). Trashed files count: a pass that
        # tidied 12 proxies is a pass that found something to do.
        self._last_run_moved = max(0, int(result.transferred or 0)) + max(
            0, int(result.deleted or 0))
        # Ahead of every return below, including the stop-mid-transfer one: a
        # pass that was killed halfway still moved whatever it moved, and a
        # breaker that only counts tidy passes is a breaker that a flapping
        # link can walk straight past (item 9).
        tripped = self._account_pass(result, subpath, local_proxies)

        if returncode != 0 and self._stop_event.is_set():
            # SYNC-5 (2026-08-14): stop() terminated this child mid-transfer,
            # so rclone's non-zero exit says "we killed it", not "the lane
            # failed" -- the same reasoning _stand_down_status already carries
            # for the pre-spawn cancellation ("a lane that was told to stop did
            # not fail"). It used to fall through to STATE_ERROR with
            # last_error="rclone exited 1", which painted the editor's lane red
            # on the fleet grid for a deliberate sign-out; for lane B in managed
            # mode that red was also the LAST status the lane ever published,
            # because the stop latch then swallowed every later run (SYNC-1).
            log.info(
                "%s: run ended by stop() (rclone exited %s) -- standing down, not failing",
                self.name, returncode,
            )
            status = self._stand_down_status("stopped mid-transfer")
            self._notify_trash(result)
            return self._breaker_stand_down() if tripped else status

        # BEFORE the lock: _take_pending_stall takes _lock itself, and
        # threading.Lock is not reentrant.
        stall_detail = self._take_pending_stall()
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
            #
            # FIRST, ahead of the exit-code chain: the watchdog killed this
            # child (SYNC-1 / CR-91), so its exit code says "we killed it"
            # and its stderr says nothing about why. The stall sentence is
            # the only informative thing this pass has, and unlike the
            # stop() case above it IS a failure -- the whole point is that a
            # wedged lane becomes visible instead of sitting green forever.
            if stall_detail:
                self._status.state = STATE_ERROR
                self._status.last_error = stall_detail
                self._status.detail = stall_detail
            elif returncode == RCLONE_EXIT_MAX_DURATION and max_duration_seconds:
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
                # The only LOCAL trace of a red lane. Until 2026-08-14 this
                # branch set STATE_ERROR and returned in silence -- the
                # failure reached the dashboard and nowhere else, so the
                # editor's own machine held no record of a lane the fleet
                # grid was painting red. Tracing one lane A failure (rclone
                # asking for a doubly-escaped fullwidth name, `‛‛：`, that
                # exists on no disk) meant reading the dashboard's sqlite by
                # hand and then hand-running candidate commands, because
                # companion.log knew nothing about it.
                #
                # The argv goes in deliberately: WHICH FLAGS the failing run
                # actually carried is the first question every time, and
                # --local-encoding in particular decides whether a fullwidth
                # yt-dlp name resolves at all (see LOCAL_ENCODING).
                log.error(
                    "%s: rclone exited %s -- %s\n  argv: %s",
                    self.name, returncode, self._status.last_error, " ".join(cmd),
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
        if tripped:
            # The pass itself is over and its status was just published; the
            # breaker's sentence has to be the one the editor and the fleet
            # grid end up holding, or the lane reads "transferred 0 file(s)"
            # while proxy download is stopped.
            return self._breaker_stand_down()
        self._maybe_prune_trash()
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

    # -- the free-space floor (SYS-5 / SYNC-7, sweep 2026-08-28) ----------
    def _check_disk_floor(self) -> Optional[str]:
        """One `shutil.disk_usage` on the sync drive. Returns the park
        reason, or None.

        Never raises, and a measurement that FAILS parks nothing: the latch
        keeps whatever state it had (see DiskFloorLatch.check). Lane B only --
        lane A writes to the NAS, whose capacity is the server's problem and
        the collector's to poll."""
        if self.direction != DIRECTION_DOWN or self.disk_floor is None:
            return None
        if not getattr(self.disk_floor, "enabled", True):
            return None
        try:
            free = self._free_bytes_fn(self.local_root)
        except Exception:
            log.debug("%s: could not measure free space", self.name, exc_info=True)
            free = None
        try:
            return self.disk_floor.check(free)
        except Exception:
            log.exception("%s: the free-space floor check failed", self.name)
            return None

    def _disk_stand_down(self, reason: str) -> LaneStatus:
        """Park lane B for a nearly-full drive, with its own sentence.

        STATE_PAUSED for the breaker's reasons exactly: the lane is not
        broken, and lanes A and C must keep running -- an editor whose disk
        is full still needs their originals to reach the NAS, which is also
        the only thing that makes it safe for them to delete anything."""
        with self._lock:
            self._status.state = STATE_PAUSED
            self._status.transferring = 0
            self._status.queued = 0
            self._status.speed_bps = None
            self._status.eta_seconds = None
            self._status.transfers = []
            self._status.current_project = None
            self._status.last_error = None
            self._status.detail = f"NOT DOWNLOADING (disk): {reason}"
        return self.status()

    # -- circuit breaker (COMMERCIAL_READINESS.md item 9, 2026-08-17) -----
    def _breaker_stand_down(self) -> LaneStatus:
        """Park lane B with the breaker's own sentence.

        STATE_PAUSED, deliberately: STATE_ERROR would paint the fleet grid
        red and read as "the lane is broken", when the truth is "the lane
        was stopped on purpose and needs a human". The sequencer keeps
        rotating -- lanes A and C are untouched by a lane B trip, which is
        the entire point of a breaker rather than a shutdown."""
        reason = self.breaker.reason if self.breaker is not None else "stopped"
        with self._lock:
            self._status.state = STATE_PAUSED
            self._status.transferring = 0
            self._status.queued = 0
            self._status.speed_bps = None
            self._status.eta_seconds = None
            self._status.transfers = []
            self._status.current_project = None
            self._status.last_error = None
            self._status.detail = f"STOPPED (safety): {reason}"
        return self.status()

    def _backup_dir_bytes(self) -> int:
        """Bytes this run moved into its own --backup-dir. Cheap: one run's
        directory, not the whole trash. Reads _last_backup_dir WITHOUT
        clearing it -- _notify_trash still needs it."""
        backup_dir = self._last_backup_dir
        if not backup_dir:
            return 0
        total = 0
        try:
            for dirpath, _dirnames, filenames in os.walk(backup_dir):
                for name in filenames:
                    try:
                        total += os.path.getsize(os.path.join(dirpath, name))
                    except OSError:
                        pass
        except OSError:
            return 0
        return total

    def _trashed_this_pass(self) -> list[tuple[str, int, str]]:
        """(basename, size, rel_path) for every file this run put in its
        --backup-dir.

        `rel_path` is posix and relative to the backup dir, which rclone
        mirrors from the sync DESTINATION root -- i.e. the same origin the
        remote listing's paths have (comp-lanes-ab-3, 2026-08-21).

        Reads _last_backup_dir WITHOUT clearing it, exactly as
        _backup_dir_bytes does and for the same reason: _notify_trash runs
        after the accounting and still needs it."""
        backup_dir = self._last_backup_dir
        out: list[tuple[str, int, str]] = []
        if not backup_dir:
            return out
        base = Path(backup_dir)
        try:
            for dirpath, _dirnames, filenames in os.walk(backup_dir):
                for name in filenames:
                    full = Path(dirpath) / name
                    try:
                        size = full.stat().st_size
                    except OSError:
                        continue
                    try:
                        rel = full.relative_to(base).as_posix()
                    except ValueError:
                        rel = name
                    out.append((name, size, rel))
        except OSError:
            return out
        return out

    def _count_relocations(self, subpath: Optional[str]) -> int:
        """How many of this pass's trashed files are still on the NAS, under
        a different path (KNOWN_BUGS CR-44, 2026-08-20).

        Called by the breaker, and only when a pass is about to trip it. An
        editor who drags `Interviewees/Creator_Interviews` into `B-roll/`
        deletes nothing, but every proxy under it vanishes from the path
        lane B is syncing, and the breaker used to read that as the tree
        being emptied (ruskin's PC, 2026-08-19: 100 files in one pass,
        stopped for a day, and every byte was still on the server).

        Two shapes count as "not a deletion":

        1. the file is on the NAS under ANOTHER path at the same
           basename+size -- a move, which is what CR-44 was about;
        2. the file is on the NAS at the SAME relative path, any size
           (comp-lanes-ab-3, 2026-08-21). A trashed file's own remote path
           was assumed gone by construction, and for a `sync` alone it is --
           but lane B carries `--min-age 120s`, which hides a proxy the NAS
           REWROTE in the last two minutes from the source listing while the
           editor's older local copy stays on the destination side, so rclone
           moves it aside without replacing it. Same for a plain overwrite,
           which --backup-dir also routes through the trash. Neither is the
           server losing a file, and a bulk re-render (same names, new sizes,
           fresh mtimes) otherwise trips the breaker on ~60 files that are
           all sitting on the NAS -- which the basename+size rule cannot
           excuse, because a re-encode changes the size.

        Returns 0 on any failure: see LaneBBreaker._count_relocations for why
        that is the safe direction.
        """
        trashed = self._trashed_this_pass()
        if not trashed:
            return 0
        remote_paths: set[str] = set()
        remote_files = list_remote_files(
            self.rclone_path, self.remote, self.remote_root, subpath,
            run_fn=self._remote_list_fn, paths_out=remote_paths,
        )
        if not remote_files:
            # None = the listing failed, {} = the remote really is empty.
            # Neither is evidence of a move, and the empty case is the one
            # the breaker exists for.
            return 0
        # SYNC-3 (resilience sweep 2026-08-28): both sides fold to NFC before
        # the comparison. The trashed paths came off the LOCAL disk (NFD on a
        # Mac), the remote ones off the NAS (NFC), so before this every path
        # with a diacritic scored as a deletion and the breaker tripped on a
        # benign reorganisation. Comparison only -- nothing here opens a file.
        remote_keys = {nfc_key(p) for p in remote_paths}
        remote_by_name: dict[str, set[int]] = {}
        for name, sizes in remote_files.items():
            remote_by_name.setdefault(nfc_key(name), set()).update(sizes)
        relocated = 0
        for name, size, rel in trashed:
            if rel and nfc_key(rel) in remote_keys:
                relocated += 1
            elif size in remote_by_name.get(nfc_key(name), ()):
                relocated += 1
        return relocated

    def check_remote_root(self) -> bool:
        """Probe `remote_root` ITSELF for the breaker's marker directories.

        sync-safety-5 (2026-08-21). `LaneBBreaker.check_remote` only applies
        the marker rule to the WHOLE-TREE scope (`if not key`), and in
        managed mode every pass names a project subpath -- so the one
        pre-flight that catches a `remote_root` pointing at the wrong dataset
        has never run on a managed fleet, while SYNC_SAFETY.md credits it
        with exactly that. One `lsf` of one directory, cached for the process
        once it passes: a root that holds `Projects/` does not stop holding
        it mid-run, and the per-project probes cover everything below.

        Returns True when the root looks like the tree (including when there
        is nothing to check, or the listing failed -- a failed listing is
        never a trip, see check_remote), False when the breaker tripped.
        Never raises."""
        if self.direction != DIRECTION_DOWN or self.breaker is None:
            return True
        if self._remote_root_checked or not self.breaker.marker_dirs:
            return True
        try:
            entries = list_remote_top(
                self.rclone_path, self.remote, self.remote_root, None,
                run_fn=self._remote_list_fn,
            )
            if entries is None:
                return True
            tripped = self.breaker.check_remote("", entries) is not None
        except Exception:
            log.exception("%s: the remote_root marker probe failed", self.name)
            return True
        if not tripped:
            self._remote_root_checked = True
        return not tripped

    def last_run_moved(self) -> int:
        """Files the last run transferred or trashed (ops-efficiency-2)."""
        return self._last_run_moved

    def _account_pass(
        self, result: RcloneRunResult, subpath: Optional[str], local_proxies: int
    ) -> bool:
        """Feed one lane B pass to the breaker. Returns True if it TRIPPED.

        Never raises: the accounting is a safety device, and a safety device
        that can fail the run it guards is worse than none."""
        if self.direction != DIRECTION_DOWN or self.breaker is None:
            return False
        try:
            scope = str(subpath or "").replace("\\", "/").strip("/")
            return self.breaker.note_pass(
                scope, result.deleted, self._backup_dir_bytes(), local_proxies,
                relocation_probe=lambda: self._count_relocations(subpath),
            ) is not None
        except Exception:
            log.exception("%s: breaker accounting failed", self.name)
            return False

    def resume_after_trip(self, by: str = "tray", request_id: Optional[str] = None) -> bool:
        """Operator clears the breaker (tray action, or the dashboard's
        standing [ RESUME ] request). Also re-arms the lane's stop latch,
        because a trip that happened during a sign-out leaves both latched
        and clearing one is not obviously enough.

        `request_id` is passed straight to the breaker, which applies any one
        id exactly once -- the dashboard's request rides every report reply
        until an admin clears it (comp-lanes-ab-2, 2026-08-21)."""
        if self.breaker is None:
            return False
        cleared = self.breaker.resume(by, request_id=request_id)
        if cleared:
            with self._lock:
                self._status.state = STATE_IDLE
                self._status.detail = "proxy download resumed"
        return cleared

    # -- .ccsync-trash retention (item 9) ---------------------------------
    def _maybe_prune_trash(self) -> None:
        """Run the retention policy at most once per interval. Lane B only:
        the trash belongs to lane B's --backup-dir and nothing else writes
        it. Never raises."""
        if self.direction != DIRECTION_DOWN or self._trash_prune_interval <= 0:
            return
        now = time.monotonic()
        if (self._last_trash_prune_at is not None
                and now - self._last_trash_prune_at < self._trash_prune_interval):
            return
        self._last_trash_prune_at = now
        try:
            summary = lane_guard.prune_trash(
                self.local_root,
                max_age_days=self._trash_max_age_days,
                max_bytes=self._trash_max_bytes,
                breaker=self.breaker,
                # SYNC-16 / SYNC-7: disk pressure is the third trigger, and
                # the one that matters on the machine whose lane B keeps
                # failing -- the floor and the prune are the same number.
                min_free_bytes=(self.disk_floor.min_free_bytes
                                if self.disk_floor is not None else 0),
                free_bytes_fn=self._free_bytes_fn,
            )
            trash = scan_trash_dir(self.local_root)
            if trash is not None:
                summary = {**summary, **trash}
            with self._lock:
                self._trash_summary = summary
        except Exception:
            log.exception("%s: trash prune failed", self.name)

    def trash_report(self) -> Optional[dict]:
        """Last trash scan/prune summary ({"count","bytes","removed",...}),
        or None before the first prune cycle. The tray's "how much is in
        trash" line and the report's `sync_guard.trash` read this."""
        with self._lock:
            return dict(self._trash_summary) if self._trash_summary else None

    def sync_guard_report(self) -> dict:
        """This lane's contribution to the report's `sync_guard` section."""
        out: dict = {}
        if self.breaker is not None:
            try:
                out["lane_b_breaker"] = self.breaker.report()
            except Exception:
                log.exception("%s: breaker report failed", self.name)
        if self.disk_floor is not None:
            try:
                # SYS-5 / SYNC-7: the LATCH, not the measurement. The disk
                # numbers themselves ride `sync_guard.disk`, measured once per
                # heavy tick in app.py; this is why lane B is parked.
                out["disk_floor"] = self.disk_floor.report()
            except Exception:
                log.exception("%s: disk floor report failed", self.name)
        trash = self.trash_report()
        if trash:
            out["trash"] = trash
        if self._size_mismatches:
            out["skipped_exists"] = self._size_mismatches
        # SYNC-1 (resilience sweep 2026-08-28): the last wedged rclone this
        # machine killed. Read through stall_record(), so it survives the
        # restart that follows the symptom and so a LANE A stall reaches the
        # report through the one place app.py asks for a guard section.
        # Absent when nothing has ever stalled -- an absent key is how "no
        # lane has ever had to be killed here" is spelled.
        stalled = self.stall_report()
        if stalled:
            out["stalled"] = stalled
        return out

    # -- spawn cancellation (KNOWN_BUGS B13) ------------------------------
    def _raise_if_stopping(self, what: str) -> None:
        """Stand down if stop() has landed. Caller holds the spawn lock."""
        if self._stop_event.is_set():
            log.info(
                "%s: %s cancelled -- stop() landed before rclone was started",
                self.name, what,
            )
            raise SpawnCancelled(f"{self.name}: {what} cancelled by stop()")

    def _stand_down_status(self, detail: str = "stopped before this pass started") -> LaneStatus:
        """Clear the SYNCING bookkeeping a cancelled run had already set.

        Deliberately IDLE, not ERROR: a lane that was told to stop did not
        fail, and painting it red would make every self-upgrade/sign-out look
        like a broken lane on the grid.

        `detail` distinguishes the two stand-downs: the default is the
        pre-spawn cancellation, and SYNC-5's terminated-mid-transfer case
        passes its own so the tray does not claim a run that moved gigabytes
        never started. last_error is deliberately left alone -- a stand-down
        neither creates nor clears a lane's health history."""
        with self._lock:
            self._status.state = STATE_IDLE
            self._status.transferring = 0
            self._status.speed_bps = None
            self._status.eta_seconds = None
            self._status.transfers = []
            self._status.current_project = None
            self._status.detail = detail
        return self.status()

    # -- the stall watchdog (SYNC-1 / SYS-17, CR-91) ----------------------
    def _stall_lane_label(self, express: bool = False) -> str:
        """"A" | "B" | "express" -- the report's spelling of which lane
        stalled (the wire contract, not this module's lane names)."""
        if express:
            return "express"
        return "A" if self.direction == DIRECTION_UP else "B"

    def _progress_marker(
        self, tally: Optional[RcloneRunTally], include_bytes: bool = True
    ) -> tuple[int, int]:
        """(bytes, files) this run has moved so far.

        THE test for a hang, and it is deliberately not wall clock: a 40 GB
        original crawling over a thin uplink keeps moving this tuple and is
        never killed, while a read wedged in the kernel cannot move it at
        all. Bytes come from the --stats records _handle_stderr_line already
        parses; files from the tally beside it, so a run copying millions of
        tiny files with no stats tick yet still counts as progress."""
        # include_bytes=False for the express path: `bytes_done` on the
        # shared status belongs to the PERIODIC run, which can be moving
        # gigabytes while the express child is wedged -- borrowing its bytes
        # would hide exactly the stall we are looking for.
        done = 0
        if include_bytes:
            with self._lock:
                done = self._status.bytes_done or 0
        moved = int(getattr(tally, "transferred", 0) or 0) + int(
            getattr(tally, "deleted", 0) or 0)
        try:
            return int(done), moved
        except (TypeError, ValueError):
            return 0, moved

    def _wait_with_watchdog(
        self,
        cmd: list[str],
        proc: Any,
        tally: Optional[RcloneRunTally],
        max_duration_seconds: Optional[float],
        express: bool = False,
    ) -> int:
        """proc.wait(), but bounded -- the two lines CR-91 asked for.

        Polls instead of blocking forever, and kills the child on either
        ceiling. Nothing here changes a healthy run: a child that exits
        inside the first poll never sees the watchdog at all.

        ONE EXEMPTION, and it is the difference between this and a timeout:
        a run that is STILL MOVING BYTES is never killed, at either ceiling.
        CR-91 asks for exactly that ("bytes moved, not wall clock, is the
        test") and the cost of getting it wrong is concrete: --cutoff-mode
        SOFT lets an in-flight transfer land, so a 40 GB original on a thin
        uplink legitimately outlives any wall-clock ceiling, and SFTP
        uploads do not resume -- killing it at 25 minutes would restart it
        from byte 0 next pass, forever, and leave a `.partial` on the NAS
        each time. So the hard ceiling fires when the run is past it AND has
        moved nothing for two polls; while bytes keep arriving it logs once
        and lets the transfer finish."""
        zero_limit = zero_progress_limit_seconds(max_duration_seconds)
        hard_limit = hard_ceiling_seconds(max_duration_seconds)
        clock = self._monotonic
        spawn_lock = self._express_proc_lock if express else self._proc_lock
        what = "wedged express rclone" if express else "wedged rclone"
        started = clock()
        last_progress_at = started
        last_marker = self._progress_marker(tally, include_bytes=not express)
        over_ceiling_logged = False
        while True:
            try:
                return proc.wait(timeout=self._wait_poll_seconds)
            except subprocess.TimeoutExpired:
                pass
            except Exception:
                # A wait() that cannot be performed at all (a handle the OS
                # lost, a stand-in that does not take a timeout). Reported as
                # a failed run rather than retried forever in this loop.
                log.exception("%s: could not wait on the rclone child", self.name)
                return RCLONE_STALL_RETURNCODE
            now = clock()
            marker = self._progress_marker(tally, include_bytes=not express)
            if marker != last_marker:
                last_marker, last_progress_at = marker, now
            idle_for = now - last_progress_at
            ran_for = now - started
            # "Moving" = something arrived within the last two polls. One
            # poll would make a --stats tick landing a moment late look
            # like a stall.
            moving = idle_for < (2 * max(1.0, float(self._wait_poll_seconds)))
            if idle_for >= zero_limit:
                stalled_for, detail = idle_for, (
                    f"rclone made no progress for {int(idle_for)}s - killed")
            elif ran_for >= hard_limit and not moving:
                stalled_for, detail = ran_for, (
                    f"rclone did not exit after {int(ran_for)}s - killed")
            elif ran_for >= hard_limit:
                if not over_ceiling_logged:
                    over_ceiling_logged = True
                    log.warning(
                        "%s: rclone is past its %ds ceiling but still moving "
                        "(%s bytes / %s file(s)) -- letting it finish rather than "
                        "restarting a transfer from zero",
                        self.name, int(hard_limit), last_marker[0], last_marker[1],
                    )
                continue
            else:
                continue
            log.error(
                "%s: %s (moved %s bytes / %s file(s) in %ds)\n  argv: %s",
                self.name, detail, last_marker[0], last_marker[1], int(ran_for),
                " ".join(cmd),
            )
            self._record_stall(int(stalled_for), detail, express=express)
            with spawn_lock:
                self._terminate_child(proc, what)
            try:
                # Bounded, and it may well not answer: a process in an
                # uninterruptible kernel wait cannot be killed at all, which
                # is the hang this whole loop exists to escape. The lane
                # reports the stall either way and the OS gets the corpse.
                return proc.wait(timeout=5)
            except Exception:
                log.warning(
                    "%s: the wedged rclone did not die -- leaving it to the OS and "
                    "reporting the stall", self.name,
                )
                return RCLONE_STALL_RETURNCODE

    def _record_stall(self, seconds: int, detail: str, express: bool = False) -> None:
        """Remember (and persist) a stall this lane just killed.

        Persisted because a companion restart -- or the self-upgrade an
        editor performs while chasing the symptom -- would otherwise erase
        the only local record that anything was killed at all."""
        record = {
            "lane": self._stall_lane_label(express),
            "seconds": max(0, int(seconds)),
            "killed": True,
            "at": datetime.now(timezone.utc).isoformat(),
            "detail": detail,
        }
        with self._lock:
            self._last_stall = record
            if not express:
                # Consumed by _run_once_locked, so the pass reports the stall
                # rather than rclone's "exited -9", which says nothing.
                self._pending_stall_detail = detail
        write_stall_record(self._stall_file, record)

    def _take_pending_stall(self) -> Optional[str]:
        with self._lock:
            detail, self._pending_stall_detail = self._pending_stall_detail, None
        return detail

    def stall_record(self) -> Optional[dict]:
        """The last stall this machine detected and killed, or None.

        Falls back to the persisted file, so the answer survives a restart --
        and so lane B's sync_guard_report can carry a stall that happened on
        lane A: both lanes share the state dir, and the report has one
        `stalled` slot."""
        with self._lock:
            if self._last_stall:
                return dict(self._last_stall)
        return read_stall_record(self._stall_file)

    def stall_report(self) -> Optional[dict]:
        """`sync_guard.stalled` for the report: the wire's four keys only.

        `detail` is deliberately left off the wire -- the tray and the log
        carry the sentence; the dashboard gets the machine-readable half."""
        record = self.stall_record()
        if not record:
            return None
        out = {key: record.get(key) for key in ("lane", "seconds", "killed", "at")}
        return out if out.get("at") else None

    def abort_run(self, why: str, seconds: int = 0) -> bool:
        """End the rclone child of the run in flight, without latching the
        lane off. Returns True when there was one. Never raises.

        The sequencer's bounded lane B join calls this (SYNC-1): an un-joined
        lane B would still be writing into a project directory the next
        project's repath moves, and stop() is the wrong tool -- it sets
        _stop_event for the whole thread generation, i.e. it would leave lane
        B refusing every later pass until something restarted it. Killing
        just the child ends the pass, paints the lane red with the reason,
        and lets the next turn run normally."""
        try:
            with self._proc_lock:
                proc = self._proc
                if proc is None:
                    return False
                self._record_stall(seconds, why)
                self._terminate_child(proc, "rclone (aborted by the sequencer)")
            log.warning("%s: %s", self.name, why)
            return True
        except Exception:
            log.exception("%s: abort_run failed", self.name)
            return False

    # -- Popen-based runner with live --stats JSON parsing ---------------
    def _run_popen(
        self, cmd: list[str], max_duration_seconds: Optional[float] = None,
    ) -> tuple[int, str, RcloneRunResult]:
        """Run rclone, parsing its stderr AS IT ARRIVES.

        Returns (returncode, bounded stderr tail, incremental parse result).
        The tail is STDERR_TAIL_LINES lines, not the whole stream: see
        RcloneRunTally for why keeping all of it was a memory problem on real
        ingests (AUDIT_3 M-8).

        `max_duration_seconds` is the pass's own budget, and here it is what
        the stall watchdog's two ceilings are derived from -- see
        zero_progress_limit_seconds / hard_ceiling_seconds. A stall sets
        `self._last_stall` (and persists it) and leaves the child killed;
        _run_once_locked turns that into the lane's error state."""
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
            returncode = self._wait_with_watchdog(cmd, proc, tally, max_duration_seconds)
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
        moved = (int(getattr(tally, "transferred", 0) or 0) + int(
            getattr(tally, "deleted", 0) or 0)) if tally is not None else 0
        with self._lock:
            self._status.bytes_done = stats.get("bytes")
            self._status.bytes_total = stats.get("totalBytes")
            self._status.speed_bps = stats.get("speed")
            self._status.eta_seconds = stats.get("eta")
            self._status.transfers = self._normalize_transferring(
                stats.get("transferring"), project_slug
            )
            # SYS-1: the evidence that this lane is alive, refreshed here
            # because this is the one place real movement is observed.
            self._status.progress_token = progress_token(
                stats.get("bytes"), moved, subpath)

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
        self._announce_watch_state("The sync drive is responding again. CCSync is watching it for "
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
        """Counters for the reporter/tray (owned elsewhere). Read-only.

        `last_run_age_seconds` (SYNC-13) is what makes a DEAD express lane
        visible: the counters simply stop advancing when it wedges, and
        nothing checked that they were stale. None until the first run."""
        with self._lock:
            report = dict(self._express_status)
        report["last_run_age_seconds"] = _iso_age_seconds(report.get("last_run"))
        return report

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
        # SYNC-3 (2026-08-14): the other half of _build_command's exclusion.
        # A periodic run already in flight cannot be told to skip a path
        # claimed after it spawned, so express stands aside for anything that
        # run covers instead of racing it for the same bytes. Snapshotted once
        # per window: a run that ends mid-loop only means one more window's
        # wait for the paths already judged.
        scope = self.periodic_inflight_subpath()
        deferred_to_periodic = 0
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
            if st.st_size <= 0:
                # COMP-GUARD-1 (2026-08-14): the express twin of lane A's
                # --min-size floor, in Python because rclone REFUSES the flag
                # here -- measured against the bundled 1.74.4, `--min-size`
                # alongside `--files-from-raw` dies with the same CRITICAL
                # "overrides all other filters" that rules out --min-age and
                # --filter-from (see build_express_command). Express is
                # `copy --ignore-existing` too, so an empty upload is just as
                # permanent. Deferred rather than dropped: a file that was
                # only just created is legitimately 0 bytes for an instant,
                # and the next window sees the real ones.
                deferred[rel] = (0, first_seen)
                continue
            if scope is not None and self._relativize_to_subpath(rel, scope) is not None:
                # Deferring loses nothing: that run's own walk usually reaches
                # the file, and if it doesn't, the next window uploads it (or,
                # after EXPRESS_PENDING_MAX_SECONDS, the next periodic pass
                # does -- the give-up check above stays ahead of this one so a
                # long-running lane A can never strand a path here).
                deferred[rel] = (st.st_size, first_seen)
                deferred_to_periodic += 1
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
        if deferred_to_periodic:
            log.info(
                "%s: express deferred %d path(s) to the periodic run already in "
                "flight for %s", self.name, deferred_to_periodic, scope or "the whole tree",
            )
        return ready, deferred

    def _express_drop_moved_away(self, rels: list[str]) -> list[str]:
        """Drop the paths the server has moved away from (or refused to move)
        before they reach the --files-from-raw list.

        bug-hunt-2026-09-03 comp-sync-1: `_build_command` keeps those paths
        out of the PERIODIC run with `- /<rel>` filter rules, and an express
        run cannot carry a filter file at all (build_express_command), so
        without this the same file goes back to the NAS at the path the admin
        just cleared through lane A's other door -- permanently, since
        --ignore-existing means nothing replaces it. The excludes are asked
        for relative to local_root (`subpath=None`), which is the space
        express rels live in. Never raises: a source of excludes that cannot
        answer must not stop the upload, exactly as in _build_command.
        """
        if self.direction != DIRECTION_UP or self.extra_excludes_fn is None:
            return rels
        try:
            excludes = [
                nfc_key(str(rel)).replace("\\", "/").strip("/").lower()
                for rel in (self.extra_excludes_fn(None) or [])
            ]
        except Exception:
            log.exception("%s: extra_excludes_fn failed -- excluding nothing", self.name)
            return rels
        excludes = [rel for rel in excludes if rel]
        if not excludes:
            return rels
        kept: list[str] = []
        for rel in rels:
            key = nfc_key(str(rel)).replace("\\", "/").strip("/").lower()
            # A file-moves exclusion can name a DIRECTORY (`is_dir`), which is
            # why the prefix arm is here as well as the equality one.
            if any(key == ex or key.startswith(ex + "/") for ex in excludes):
                continue
            kept.append(rel)
        dropped = len(rels) - len(kept)
        if dropped:
            log.info(
                "%s: express kept %d path(s) the server moved away from out of this run",
                self.name, dropped,
            )
        return kept

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

        rels = self._express_drop_moved_away(rels)
        if not rels:
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
            max_duration_seconds=self._express_max_duration,
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
        # SYNC-13: this used to be `proc.stderr.read()` (blocks until EOF,
        # which a grandchild holding the write handle never gives) followed by
        # an unbounded `proc.wait()`. Same shape as _run_popen now: a daemon
        # reader we can walk away from, and a wait with the stall watchdog's
        # two ceilings on it.
        # A BIGGER cap than the periodic path's 200-line tail, and it is
        # load-bearing: the caller re-parses this text with parse_json_log to
        # count what express uploaded (and to feed the dashboard's history),
        # so a batch of up to express_max_batch files must not have its
        # earliest "Copied" records trimmed away. Still bounded, because the
        # reason _run_popen keeps a tail at all (AUDIT_3 M-8) applies here
        # too, just at a much smaller scale.
        lines: deque[str] = deque(maxlen=EXPRESS_STDERR_TAIL_LINES)
        tally = RcloneRunTally()
        abandoned = threading.Event()

        def _reader() -> None:
            try:
                if proc.stderr is None:
                    return
                for line in proc.stderr:
                    if abandoned.is_set():
                        return
                    lines.append(line)
                    text = line.strip()
                    if not text.startswith("{"):
                        continue
                    try:
                        tally.feed_record(json.loads(text))
                    except ValueError:
                        continue
            except Exception:
                log.exception(
                    "%s: express stderr reader failed -- killing rclone so the wait "
                    "cannot deadlock", self.name,
                )
                try:
                    proc.kill()
                except Exception:
                    pass

        reader_thread = threading.Thread(
            target=_reader, name=f"ccsync-{self.name}-express-reader", daemon=True
        )
        reader_thread.start()
        try:
            returncode = self._wait_with_watchdog(
                cmd, proc, tally, self._express_max_duration, express=True,
            )
        finally:
            with self._express_proc_lock:
                if self._express_proc is proc:
                    self._express_proc = None
        reader_thread.join(timeout=STDERR_READER_JOIN_SECONDS)
        if reader_thread.is_alive():
            abandoned.set()
            log.warning(
                "%s: the express rclone exited but its stderr pipe is still open "
                "after %.0fs -- continuing with a truncated log",
                self.name, STDERR_READER_JOIN_SECONDS,
            )
        try:
            stderr_text = "".join(list(lines))
        except RuntimeError:
            stderr_text = ""
        return returncode, stderr_text
