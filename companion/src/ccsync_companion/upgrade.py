"""Companion self-upgrade (notify + one-click).

The dashboard advertises the published "current" build in its report/verify
responses as a conditional `upgrade` key (absent = up to date -- see the
dashboard's api._upgrade_info). The reporter hands every report response to
UpgradeManager.note_report_response(); when an upgrade is available the tray
grows an "Update now" item, and apply() does the whole swap:

    verify the OFFLINE RELEASE SIGNATURE over the whole offered record
                                     (release_pubkey.py -- ed25519, key baked
                                      into this binary, private half on no
                                      fleet machine at all; item 4,
                                      2026-08-17). Unsigned or unverifiable
                                      is REFUSED, with no fallback: the
                                      dashboard is not a trust anchor.
    -> downgrade-floor check         (~/.ccsync/upgrade_floor.json, monotonic)
    -> transport check               (https, or plain http to tailnet/LAN only)
    -> download to <exe dir>/ccsync-companion.new[.exe] -> sha256 verify
                                     (against the SIGNED sha256)
    -> chmod 0o755                   (POSIX only -- see _make_executable)
    -> os.replace(exe, exe.old)      (a RUNNING exe can't be overwritten on
                                      Windows, but it CAN be renamed on the
                                      same volume -- hence same-dir download.
                                      macOS needs the same dance for a
                                      different reason: overwriting a running
                                      Mach-O in place breaks its pages and
                                      its ad-hoc signature)
    -> os.replace(new, exe)
    -> spawn the new exe detached    (failure here ROLLS BACK both renames
                                      and keeps the current build running)
    -> request_shutdown()

Platform shape: Windows ships `ccsync-companion.exe`; macOS ships a bare
single-file Mach-O called `ccsync-companion` (no extension, no .app bundle),
ad-hoc signed by PyInstaller -- the signature is part of the file, so it
travels through os.replace untouched. Every name and every spawn flag below
is therefore platform-derived, never hardcoded to the Windows shape.

The stale `.old` is deleted on the NEXT startup (cleanup_old_exe) because the
new process may start while the old one still holds its own image briefly.

"Different, not newer": the server only advertises when the current published
version differs from what we reported, so an admin rollback is offered to the
fleet exactly like an upgrade. The DOWNLOAD/SWAP machinery still compares
nothing -- but the WORDING must (see compare_to_running / offer_label): a
rollback offer that reads "Update available" is a one-click downgrade.

Never-raise ethos throughout, injectable I/O for tests (same conventions as
reporter.py).
"""
from __future__ import annotations

import hashlib
import ipaddress
import json
import logging
import os
import platform
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable, Optional

from . import config as config_mod
from . import release_pubkey

log = logging.getLogger("ccsync.upgrade")

# (url, headers, timeout) -> file-like response usable as a context manager.
HttpOpenFn = Callable[[str, dict, float], Any]
ReplaceFn = Callable[[Path, Path], Any]
SpawnFn = Callable[[Path], Any]

# Generous: editors may be on slow links and the exe is ~20 MB.
DOWNLOAD_TIMEOUT = 600.0
_NEW_STEM = "ccsync-companion.new"
# Platform-neutral: appended to whatever the running binary is called, so it
# is `ccsync-companion.exe.old` on Windows and `ccsync-companion.old` on macOS
# without any per-platform spelling.
_OLD_SUFFIX = ".old"

# R11 (2026-08-12): how long apply() watches the child it spawned before it
# stands the running build down. The child's single-instance guard waits up
# to app.PREDECESSOR_WAIT_SECONDS for US to exit, so a child that dies inside
# this window did not lose the hand-off race -- it failed to start, and
# shutting down anyway is how a one-click update left an editor's machine
# with no companion at all (nothing retries: the Run-key autostart is
# logon-only). Short on purpose: this blocks the tray thread that clicked
# the update dialog.
CHILD_TAKEOVER_GRACE_SECONDS = 2.0
CHILD_TAKEOVER_POLL_SECONDS = 0.1
# The published exe is ~20 MB. A ceiling stops a hostile or broken response
# filling the editor's disk (there was none at all), and the free-space check
# stops a download that cannot possibly complete (AUDIT_2 §2-low).
MAX_DOWNLOAD_BYTES = 300 * 1024 * 1024
MIN_FREE_BYTES_MARGIN = 200 * 1024 * 1024
# The legacy one-line marker. Still WRITTEN alongside the JSON record below so
# a deliberate rollback to a pre-APP-5 build keeps its "Update complete"
# toast, and READ once when the JSON record is absent (the adoption).
_VERSION_MARKER = "last_version.txt"
_VERSION_STATE = "last_version.json"
# APP-5 / REL-2 (resilience sweep 2026-08-28). A build that boots, puts a tray
# icon up and dies three minutes later used to leave the machine with a broken
# exe and no way back: `.old` was deleted on a flat 60 s timer and nothing
# counted restarts. Three starts of the SAME version inside ten minutes is the
# signature of a build that cannot stay up (Windows relaunches at each logon,
# and an editor who sees the tray vanish restarts it by hand faster than
# that); two would fire on one crash plus one manual restart.
CRASH_LOOP_STARTS = 3
CRASH_LOOP_WINDOW_SECONDS = 600.0
# How long the rollback copy is kept when NO report is ever accepted. The
# health signal is one accepted dashboard report (app._on_report_response,
# APP-1's channel); this is the fallback for a machine that is off the tailnet
# or whose dashboard is down, and it is deliberately long enough to cover the
# window in which a bad build actually manifests.
OLD_EXE_KEEP_SECONDS = 3600.0
OLD_EXE_POLL_SECONDS = 30.0
# REL-8: how a machine that CANNOT take a build stops hammering the NAS.
# 10 min -> 1 h -> 6 h, then 6 h onwards, and after MAX_UPGRADE_ATTEMPTS
# failures of the same version it stops trying and says so on the tray. The
# counter is persisted because the old flat 600 s timer was in-memory only:
# a machine whose AV quarantined every download pulled ~20 MB every ten
# minutes indefinitely, and a restart reset even that.
ATTEMPTS_FILENAME = "upgrade_attempts.json"
UPGRADE_BACKOFF_SECONDS = (600.0, 3600.0, 21600.0)
MAX_UPGRADE_ATTEMPTS = 8
# The `last_error` codes carried in the report, so the dashboard can tell an
# AV quarantine from a captive portal from a wrong-arch binary (REL-16)
# without parsing a log.
ERROR_DOWNLOAD = "download-failed"
ERROR_SHA = "sha-mismatch"
ERROR_SPACE = "no-space"
ERROR_REFUSED = "refused"
ERROR_SWAP = "swap-failed"
ERROR_EXEC = "exec-failed"


def arch_key() -> str:
    """This machine's CPU architecture, normalised (REL-16).

    platform.machine() spells the same CPU `AMD64` on Windows and `x86_64` on
    macOS, and `arm64`/`aarch64` for Apple silicon. The channel needs ONE
    spelling per architecture, because the discriminator used to be `platform`
    alone: an Intel Mac reported `macos` and was offered the arm64 build
    GitHub's macos-latest runner produced, which downloads, verifies, swaps in
    and cannot exec. Anything unrecognised is passed through lowercased rather
    than guessed at -- the dashboard treats an arch it does not know as "offer
    nothing", which is the safe direction."""
    try:
        machine = (platform.machine() or "").strip().lower()
    except Exception:
        return "unknown"
    if machine in ("amd64", "x86_64", "x64"):
        return "x86_64"
    if machine in ("arm64", "aarch64", "armv8", "armv8l"):
        return "arm64"
    return machine or "unknown"


# ------------------------------------------------- the start record (APP-5)

def _read_json(path: Path) -> dict:
    """A JSON object off disk, or {}. Never raises: every caller here treats
    "we know nothing" as a valid answer, and a truncated state file must never
    be able to stop the companion starting."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _write_json(path: Path, data: dict) -> bool:
    """tmp + os.replace, like identity.save_identity: a half-written record
    that fails to parse reads as "we know nothing", and for the crash-loop
    counter that is the one answer this file must not invent. Never raises."""
    try:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        os.replace(tmp, path)
        return True
    except Exception:
        log.debug("upgrade: could not write %s", path, exc_info=True)
        return False


def version_state_path(state_dir: Path) -> Path:
    return Path(state_dir) / _VERSION_STATE


def read_version_state(state_dir: Path) -> dict:
    """The persisted start record, adopting the legacy one-line marker once.

    {version, starts, first_start_at, last_clean_shutdown, previous_version}.
    An older build wrote only `last_version.txt`, so a machine upgrading INTO
    this build has its previous version there and nowhere else -- and
    `previous_version` is what the crash-loop guard checks against the
    downgrade floor before it restores anything."""
    state_dir = Path(state_dir)
    record = _read_json(version_state_path(state_dir))
    if record.get("version"):
        return record
    try:
        legacy = (state_dir / _VERSION_MARKER).read_text(encoding="utf-8").strip()
    except Exception:
        legacy = ""
    return {"version": legacy} if legacy else {}


def note_version_start(state_dir: Path, now: Optional[float] = None) -> dict:
    """Record this start and answer what it MEANS. Never raises.

    Returns {version, previous_version, starts, first_start_at, upgraded,
    crash_loop}. `upgraded` is the old boolean return: "is this the first
    start on a build we have not run before", which drives the "Update
    complete" toast and must not be derived from whether cleanup_old_exe()
    managed to unlink an `.old` (AUDIT_2 CORE-H6). `starts` counts launches of
    the SAME version and resets on a clean shutdown, so `crash_loop` means
    "this build has come up three times in ten minutes without once shutting
    down cleanly" -- i.e. it is not staying up (APP-5 / REL-2)."""
    stamp = time.time() if now is None else float(now)
    record: dict[str, Any] = {
        "version": config_mod.VERSION,
        "previous_version": "",
        "starts": 1,
        "first_start_at": stamp,
        "last_clean_shutdown": None,
        "upgraded": False,
        "crash_loop": False,
    }
    try:
        state_dir = Path(state_dir)
        state_dir.mkdir(parents=True, exist_ok=True)
        previous = read_version_state(state_dir)
        prev_version = str(previous.get("version") or "").strip()
        if prev_version != config_mod.VERSION:
            # A first-ever run (no record at all) is not an upgrade.
            record["upgraded"] = bool(prev_version)
            record["previous_version"] = prev_version
        else:
            record["previous_version"] = str(previous.get("previous_version") or "")
            started = previous.get("first_start_at")
            started = float(started) if isinstance(started, (int, float)) else None
            starts = previous.get("starts")
            starts = int(starts) if isinstance(starts, (int, float)) else 0
            clean = bool(previous.get("last_clean_shutdown"))
            # A clean shutdown resets the count: the editor quitting the tray
            # (or a reboot) is not a crash, and counting it would revert a
            # perfectly good build on the third normal restart of a morning.
            # So does a stale window -- three starts spread over a week say
            # nothing about this build's health.
            if (clean or starts <= 0 or started is None
                    or (stamp - started) > CRASH_LOOP_WINDOW_SECONDS):
                record["starts"] = 1
                record["first_start_at"] = stamp
            else:
                record["starts"] = starts + 1
                record["first_start_at"] = started
        record["crash_loop"] = bool(
            record["starts"] >= CRASH_LOOP_STARTS
            and (stamp - float(record["first_start_at"])) <= CRASH_LOOP_WINDOW_SECONDS
        )
        _write_json(version_state_path(state_dir), {
            key: record[key] for key in
            ("version", "previous_version", "starts", "first_start_at",
             "last_clean_shutdown")
        })
        # Still written so a pre-APP-5 build can read it after a rollback.
        try:
            marker = state_dir / _VERSION_MARKER
            tmp = marker.with_name(marker.name + ".tmp")
            tmp.write_text(config_mod.VERSION, encoding="utf-8")
            os.replace(tmp, marker)
        except Exception:
            log.debug("upgrade: could not write the legacy version marker", exc_info=True)
    except Exception:
        log.debug("note_version_start failed", exc_info=True)
    return record


def note_clean_shutdown(state_dir: Path, now: Optional[float] = None) -> None:
    """Stamp this run as having ended on purpose, so the next start does not
    count it towards the crash loop. Never raises -- it is called from
    CompanionApp.shutdown(), where an exception would be the process exiting
    past its own teardown."""
    stamp = time.time() if now is None else float(now)
    try:
        path = version_state_path(Path(state_dir))
        record = _read_json(path)
        if str(record.get("version") or "") != config_mod.VERSION:
            # Not our record (a rollback wrote it for the build coming up):
            # leave it alone rather than stamping someone else's row.
            return
        record["last_clean_shutdown"] = stamp
        _write_json(path, record)
    except Exception:
        log.debug("note_clean_shutdown failed", exc_info=True)


# ------------------------------------------- the attempt ledger (REL-8)
#
# One record, under the STATE dir (lane scratch that is safe to delete -- an
# operator who removes it has asked for the retries to start again), covering
# both update paths: unattended (site [features] auto_update) and the admin's
# push. The dashboard re-sends a push on EVERY report until the machine
# reports the new version, so without this the only thing between a machine
# that cannot take a build and the NAS was a 600 s in-memory timer.


def attempts_path(state_dir: Path) -> Path:
    return Path(state_dir) / ATTEMPTS_FILENAME


def read_attempts(path: Path) -> dict:
    """{version, attempts, last_error, last_attempt_at, reverted_from,
    reverted_at, reverted_announced}, or {}. Never raises."""
    return _read_json(path)


def note_upgrade_attempt(path: Path, version: Any, error: str,
                         now: Optional[float] = None) -> dict:
    """Count one FAILED attempt at `version` and persist it. Returns the
    record. A different target version resets the count: a new build is a new
    question, and an admin who publishes a fix must not find the machine still
    serving out the old build's six-hour back-off."""
    stamp = time.time() if now is None else float(now)
    wanted = str(version or "").strip()
    record = read_attempts(path)
    if str(record.get("version") or "") != wanted:
        record = {key: record[key] for key in
                  ("reverted_from", "reverted_at", "reverted_announced")
                  if key in record}
        record["version"] = wanted
        record["attempts"] = 0
    try:
        attempts = int(record.get("attempts") or 0)
    except (TypeError, ValueError):
        attempts = 0
    record["attempts"] = attempts + 1
    record["last_error"] = str(error or "") or None
    record["last_attempt_at"] = stamp
    _write_json(path, record)
    return record


def clear_upgrade_attempts(path: Path, version: Any = None) -> None:
    """Forget the failures for `version` (or for whatever is recorded when no
    version is given). Called when the machine comes up ON the version it was
    trying to take: the attempt succeeded, however many tries it cost. The
    revert keys are deliberately preserved -- the dashboard has not seen them
    yet."""
    record = read_attempts(path)
    if not record:
        return
    wanted = str(version or "").strip()
    if wanted and str(record.get("version") or "") != wanted:
        return
    for key in ("version", "attempts", "last_error", "last_attempt_at"):
        record.pop(key, None)
    _write_json(path, record)


def upgrade_backoff_seconds(attempts: Any) -> float:
    """How long to wait after `attempts` consecutive failures: 10 min, then
    1 h, then 6 h for every failure after that."""
    try:
        count = int(attempts or 0)
    except (TypeError, ValueError):
        count = 0
    if count <= 0:
        return 0.0
    index = min(count, len(UPGRADE_BACKOFF_SECONDS)) - 1
    return UPGRADE_BACKOFF_SECONDS[index]


def upgrade_attempts_exhausted(record: Any, version: Any) -> bool:
    """True when this machine has given up on `version` (REL-8's cap).

    Only ever true for the version the failures are recorded against: a new
    offer is always tried, because the whole point of publishing a fix is that
    the machine takes it."""
    if not isinstance(record, dict):
        return False
    if str(record.get("version") or "") != str(version or "").strip():
        return False
    try:
        return int(record.get("attempts") or 0) >= MAX_UPGRADE_ATTEMPTS
    except (TypeError, ValueError):
        return False


def upgrade_retry_due(record: Any, version: Any, now: Optional[float] = None) -> bool:
    """Has the back-off for `version` elapsed? Never raises.

    Wall clock, not monotonic, because the point is that a RESTART does not
    reset it -- an AV that quarantines every download also tends to come with
    a machine its owner keeps restarting."""
    if not isinstance(record, dict):
        return True
    if str(record.get("version") or "") != str(version or "").strip():
        return True
    last = record.get("last_attempt_at")
    if not isinstance(last, (int, float)) or isinstance(last, bool):
        return True
    stamp = time.time() if now is None else float(now)
    # A clock that went BACKWARDS (a laptop back from sleep with a bad RTC)
    # must not park the machine for six hours: a negative age reads as due.
    age = stamp - float(last)
    if age < 0:
        return True
    return age >= upgrade_backoff_seconds(record.get("attempts"))


def note_reverted_from(path: Path, version: Any, now: Optional[float] = None) -> None:
    """Leave the crash-loop revert where the RESTORED build will find it: it
    is the build that comes up next which has to toast it and report it, not
    the one on its way out. Never raises."""
    stamp = time.time() if now is None else float(now)
    record = read_attempts(path)
    record["reverted_from"] = str(version or "")
    record["reverted_at"] = stamp
    record["reverted_announced"] = False
    _write_json(path, record)


def clear_reverted_from(path: Path) -> None:
    """Drop the revert marker once the dashboard has seen it (one accepted
    report). Never raises."""
    record = read_attempts(path)
    if not record.get("reverted_from") and "reverted_at" not in record:
        return
    for key in ("reverted_from", "reverted_at", "reverted_announced"):
        record.pop(key, None)
    _write_json(path, record)


def mark_revert_announced(path: Path) -> None:
    """The editor has been told once. The marker itself stays until a report
    carries it."""
    record = read_attempts(path)
    if not record.get("reverted_from"):
        return
    record["reverted_announced"] = True
    _write_json(path, record)


def upgrade_report(record: Any, starts_this_version: Any = 1) -> dict:
    """The `sync_guard.upgrade` block (REL-8 telemetry, REL-2's revert).

    Always sent, including the all-zero shape: "this machine has never failed
    an update" is an answer the fleet grid needs, and an absent section would
    be indistinguishable from a companion too old to send one."""
    record = record if isinstance(record, dict) else {}
    try:
        attempts = int(record.get("attempts") or 0)
    except (TypeError, ValueError):
        attempts = 0
    try:
        starts = int(starts_this_version or 1)
    except (TypeError, ValueError):
        starts = 1
    last_at = record.get("last_attempt_at")
    return {
        "version": str(record.get("version") or "") or None,
        "attempts": attempts,
        "last_error": record.get("last_error") or None,
        "last_attempt_at": (_iso_utc(last_at)
                            if isinstance(last_at, (int, float))
                            and not isinstance(last_at, bool) else None),
        "reverted_from": str(record.get("reverted_from") or "") or None,
        "starts_this_version": starts,
    }


def _iso_utc(stamp: Any) -> Optional[str]:
    """An epoch seconds value as the ISO-8601 UTC spelling the dashboard's own
    received_at uses (reporter._iso_utc's twin, kept here so upgrade.py stays
    importable without the reporter)."""
    try:
        return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(float(stamp)))
    except Exception:
        return None


def same_origin(url: str, base_url: str) -> bool:
    """True when `url` is relative, or shares scheme+host+port with `base_url`.

    `upgrade.url` arrives inside a plain-HTTP /api/v1/report response, and
    the sha256 that "verifies" the download comes from that SAME response --
    so anyone able to answer or alter one report response could hand the
    companion an arbitrary exe plus its matching hash, which is then renamed
    over the running companion and launched detached. Tailnet-only limits
    exposure; there was no origin check at all (AUDIT_2 CORE-M10)."""
    if not url:
        return False
    parsed = urllib.parse.urlparse(url)
    if not parsed.scheme and not parsed.netloc:
        return True  # relative -- resolved against dashboard_url below
    base = urllib.parse.urlparse(str(base_url or "").strip())
    if not base.netloc:
        return False
    return (parsed.scheme.lower(), parsed.netloc.lower()) == (
        base.scheme.lower(), base.netloc.lower()
    )


# ------------------------------------------------- signature + floor + transport
#
# COMMERCIAL_READINESS.md item 4 (2026-08-17). Everything above this point
# defends the CHANNEL: the URL must be on the dashboard's own origin, no
# redirect may move it, the body must match an advertised sha256. None of it
# defends against the dashboard itself -- and on a customer install the
# dashboard is a container on someone else's NAS, reachable by whoever holds
# that NAS. The offer is now a record signed OFFLINE by a key that exists on
# no fleet machine, verified here before a single byte is downloaded.

# Written under the config dir (~/.ccsync), NOT the state dir: state/ is
# lane scratch that is safe to delete, and deleting the floor is the one
# operator action that un-blocks a downgrade (see docs/RELEASE.md).
FLOOR_FILENAME = "upgrade_floor.json"


def floor_path(cfg: Any) -> Path:
    """Where this machine remembers the highest min_version it has accepted.

    config_mod.CONFIG_DIR, the directory identity.json and eula_accepted.json
    already use -- NOT the log's directory (comp-app-core-5, 2026-08-21). It
    was derived from resolved_log_path, which honours config.toml's
    `log_path`, so on a machine whose log had been redirected to a second
    drive the floor lived there too: the deletion docs/RELEASE.md prescribes
    (and this module's own comments describe) removed a file that was not
    there, and editing `log_path` silently moved the floor to a new, empty
    location -- a monotonic guarantee that could be reset by a config edit is
    not one."""
    return config_mod.CONFIG_DIR / FLOOR_FILENAME


def legacy_floor_path(cfg: Any) -> Path:
    """Where the floor lived before comp-app-core-5 (2026-08-21): beside the
    log. Identical to floor_path() on every machine with a default log_path,
    which is every machine in the field."""
    return config_mod.resolved_log_path(cfg or {}).parent / FLOOR_FILENAME


def adopt_legacy_floor(cfg: Any, path: Path) -> str:
    """Carry a floor written under the old log-dir location forward, once.

    Without this, moving the file (above) would LOWER the floor to nothing on
    exactly the machines the move was meant to help -- and the floor only
    ever goes up. note_floor is monotonic, so this is safe to run on every
    start; it never raises."""
    try:
        legacy = Path(legacy_floor_path(cfg))
        if legacy == Path(path):
            return read_floor(path)
        remembered = read_floor(legacy)
        if not remembered:
            return read_floor(path)
        return note_floor(path, remembered)
    except Exception:
        log.debug("upgrade: could not adopt the legacy downgrade floor", exc_info=True)
        return ""


def read_floor(path: Path) -> str:
    """The remembered floor, or "" when there is none. Never raises: an
    unreadable or corrupt floor file means "no floor", because the
    alternative -- refusing every update because a JSON file got truncated --
    strands the machine on a build that can never be fixed."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        value = str(data.get("min_version") or "").strip()
        return value if parse_version(value) is not None else ""
    except Exception:
        return ""


def note_floor(path: Path, min_version: Any) -> str:
    """Raise the floor to `min_version` if that is higher, and persist it.
    Returns the floor in force afterwards. Never raises.

    MONOTONIC BY DESIGN. The floor only ever goes up, and no signed record can
    lower it -- otherwise the one thing an attacker needs is a copy of an old,
    genuinely-signed record with a low min_version, and the whole mechanism
    unwinds itself. That does mean a deliberate rollback below the floor
    cannot be done from the dashboard at all: the operator deletes
    ~/.ccsync/upgrade_floor.json on the machine, which is a hands-on act on
    each affected box, which is the point (docs/RELEASE.md)."""
    path = Path(path)
    current = read_floor(path)
    offered = parse_version(min_version)
    if offered is None:
        return current
    have = parse_version(current)
    if have is not None and have >= offered:
        return current
    new = str(min_version).strip()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(
            json.dumps({"min_version": new, "updated_at": time.strftime(
                "%Y-%m-%dT%H:%M:%SZ", time.gmtime())}),
            encoding="utf-8",
        )
        os.replace(tmp, path)
        log.info("upgrade: downgrade floor raised to v%s (was %s)", new, current or "none")
    except Exception:
        # A floor we could not write is not a reason to refuse the update the
        # record came with -- it is a reason to re-raise it next time.
        log.debug("upgrade: could not persist the downgrade floor", exc_info=True)
    return new


def below_floor(version: Any, floor: str) -> bool:
    """True when `version` may not be installed given `floor`.

    An unparseable OFFER against a real floor is refused: "different, not
    newer" survives above the floor (a rollback to any version >= floor is
    still one click), but nothing gets in on the strength of a version string
    we cannot rank."""
    have = parse_version(floor)
    if have is None:
        return False
    offered = parse_version(version)
    if offered is None:
        return True
    return offered < have


def _min_version_above_own(info: Any) -> bool:
    """Does this record demand a floor its own build cannot satisfy?

    comp-app-core-3 (2026-08-21). Both halves have to parse for the answer to
    mean anything: an absent or unrankable min_version is the ordinary case
    (no floor to raise), and an unrankable version is already refused by
    below_floor. Never raises.
    """
    if not isinstance(info, dict):
        return False
    floor = parse_version(info.get("min_version"))
    offered = parse_version(info.get("version"))
    if floor is None or offered is None:
        return False
    return floor > offered


def verify_offer(
    info: Any, pubkeys: Optional[Any] = None
) -> tuple[bool, str]:
    """(ok, detail) for the release signature over an offer. Never raises."""
    if not isinstance(info, dict):
        return False, "no offer"
    return release_pubkey.verify_record(
        info, info.get("signature", ""), pubkeys=pubkeys
    )


def _host_is_local(host: str) -> bool:
    """True for a tailnet/LAN/loopback host.

    100.64.0.0/10 is the CGNAT range Tailscale hands out; *.ts.net is a
    MagicDNS name for the same thing. RFC1918 and loopback cover a LAN
    deployment, and so do the intranet name shapes a customer's NAS actually
    answers to: a single-label host (`truenas`, resolved by the search
    domain) and the .local/.lan/.internal/.home.arpa suffixes. Everything
    else -- anything that looks like a name the public DNS could resolve --
    is "the open internet" as far as this check is concerned."""
    host = (host or "").strip().lower().split("%")[0]
    if host.startswith("[") and host.endswith("]"):
        host = host[1:-1]
    if not host:
        return False
    if host == "localhost" or "." not in host:
        return True
    if host.endswith((".ts.net", ".local", ".lan", ".internal", ".home.arpa")):
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    if ip.is_loopback or ip.is_private or ip.is_link_local:
        return True
    return ip in ipaddress.ip_network("100.64.0.0/10")


def transport_ok(base_url: Any) -> tuple[bool, str]:
    """(ok, note) for the configured dashboard URL as an update transport.

    https is verified by urllib against the system trust store -- nothing
    here disables that, and nothing may.

    Plain http is allowed ONLY to a tailnet/LAN host, which is what the whole
    fleet runs on today (2026-08-17) and what the Tailscale-Serve decision
    keeps as the fallback. It is not a lie of omission: `note` is logged once
    per process so an operator reading a log can see that the confidentiality
    and freshness of the channel rest on the signature alone. Plain http to a
    PUBLIC host is refused outright -- there is no scenario where an editor's
    companion should be pulling a binary over cleartext from the internet."""
    parsed = urllib.parse.urlparse(str(base_url or "").strip())
    scheme = (parsed.scheme or "").lower()
    host = parsed.hostname or ""
    if scheme == "https":
        return True, ""
    if scheme != "http":
        return False, f"dashboard_url {base_url!r} is not http(s) -- refusing to update from it"
    if _host_is_local(host):
        return True, (
            f"update channel to {host} is plain HTTP (tailnet/LAN). Downloads are "
            f"not confidential and not TLS-authenticated; every build is accepted "
            f"only on its offline release signature. Put the dashboard behind "
            f"Tailscale Serve (docs/SERVER-SYNOLOGY.md) to close that gap."
        )
    return False, (
        f"dashboard_url {base_url!r} is plain HTTP to a PUBLIC host -- refusing to "
        f"download a companion build over it. Use https."
    )


def platform_key() -> str:
    """The dashboard's platform discriminator for this machine."""
    return {"win32": "windows", "darwin": "macos"}.get(sys.platform, "linux")


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def new_download_name() -> str:
    """The temp filename the update is streamed to, beside the running binary.

    This was hardcoded to `ccsync-companion.new.exe`, which on macOS would
    have written a Windows-shaped name next to (and then renamed it over) an
    extensionless Mach-O. Harmless on its own -- os.replace does not care what
    a file is called -- but it is the same "the exe is a .exe" assumption that
    hid the missing chmod, and a leftover `.new.exe` on a Mac is a support
    call. Derived from sys.platform, never from the advertised URL: the URL is
    server-supplied and the dashboard's macOS package path has no extension at
    all."""
    return _NEW_STEM + (".exe" if sys.platform == "win32" else "")


class _RedirectRefused(Exception):
    """An injected http_open handed us an already-followed/3xx response."""

    def __init__(self, code: int) -> None:
        super().__init__(f"update URL answered HTTP {code} (redirect) -- refused")
        self.code = code


class NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """A redirect handler that refuses every redirect.

    Returning None from redirect_request() makes urllib fall through to the
    default error handler, i.e. the 3xx surfaces as an HTTPError instead of
    being followed."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D102
        return None


def build_no_redirect_opener(*handlers) -> urllib.request.OpenerDirector:
    """An opener that will NOT follow redirects.

    same_origin() is checked once, BEFORE the request -- but
    urllib.request.urlopen follows 3xx automatically, so a dashboard answer
    of `302 Location: http://attacker/build.exe` bounced the download
    off-origin AND re-sent the X-CCSync-Token header to whatever host the
    redirect chose (urllib only strips credentials, not custom headers). The
    sha256 is no defence: it comes from the same response that supplied the
    URL, so it proves the integrity of exactly the file the redirect chose.
    The result is renamed over the running companion and launched detached
    (AUDIT_3 H-1, tightening AUDIT_2 CORE-M10).

    Extra `handlers` exist so a test can drive the real chain."""
    return urllib.request.build_opener(NoRedirectHandler, *handlers)


def default_http_open(url: str, headers: dict, timeout: float):
    req = urllib.request.Request(url, headers=headers, method="GET")
    return build_no_redirect_opener().open(req, timeout=timeout)


def redirect_status(resp: Any) -> Optional[int]:
    """The 3xx status of an already-open response, or None.

    Belt to build_no_redirect_opener's braces: `http_open` is injectable
    (tests, and any future transport), so download_and_verify checks what it
    was actually handed rather than trusting the opener alone."""
    for attr in ("status", "code"):
        value = getattr(resp, attr, None)
        try:
            if value is not None and 300 <= int(value) < 400:
                return int(value)
        except (TypeError, ValueError):
            continue
    return None


def cleanup_old_exe(exe_path: Optional[Path] = None) -> bool:
    """Delete the `<exe>.old` a previous apply() left behind. Swallows
    OSError entirely -- an AV scanner may still hold the file; we simply try
    again on the next start. At most one `.old` ever exists.

    Returns True when an `.old` was actually removed. NOTE: callers must not
    use that as "we just upgraded" -- see note_version_start(), which is what
    app.run() uses now (AUDIT_2 CORE-H6). Retries a few times because the
    usual cause of failure is a transient AV/indexer hold seconds after the
    rename."""
    try:
        if exe_path is None:
            if not is_frozen():
                return False
            exe_path = Path(sys.executable)
        old = exe_path.with_name(exe_path.name + _OLD_SUFFIX)
        if not old.exists():
            return False
        for attempt in range(3):
            try:
                old.unlink()
                log.info("upgrade: removed the previous build at %s", old)
                return True
            except OSError as exc:
                log.debug("cleanup_old_exe: attempt %d failed (%s)", attempt + 1, exc)
                time.sleep(1.0)
        log.info("cleanup_old_exe: %s is still locked; will retry next start", old)
        return False
    except Exception:
        log.debug("cleanup_old_exe failed", exc_info=True)
        return False


def old_exe_path(exe_path: Optional[Path] = None) -> Optional[Path]:
    """Where the rollback copy of the PREVIOUS build lives, or None on a
    source run. Never raises."""
    try:
        if exe_path is None:
            if not is_frozen():
                return None
            exe_path = Path(sys.executable)
        exe_path = Path(exe_path)
        return exe_path.with_name(exe_path.name + _OLD_SUFFIX)
    except Exception:
        return None


def keep_old_exe_until_healthy(
    stop_event: Any,
    healthy: Callable[[], bool],
    *,
    keep_seconds: float = OLD_EXE_KEEP_SECONDS,
    poll_seconds: float = OLD_EXE_POLL_SECONDS,
    clock: Callable[[], float] = time.monotonic,
    cleanup: Callable[[], bool] = cleanup_old_exe,
) -> str:
    """Block until this build has proven itself, then delete `<exe>.old`.

    Returns why the rollback copy became expendable, or "" when the process
    is shutting down first (the `.old` then survives to the next start, which
    is the whole point: a build that never got a report in and never stayed up
    an hour is exactly the one whose predecessor must still be on disk).

    APP-5 / REL-2, replacing `threading.Timer(60.0, cleanup_old_exe)`. Sixty
    seconds is shorter than every failure mode this guard is for: a Tk fault
    in the first dialog, an exception on a code path only one editor's config
    reaches, a lane touching a surrogate path. Never raises."""
    deadline = clock() + max(0.0, float(keep_seconds))
    while True:
        reason = ""
        try:
            if healthy():
                reason = "the dashboard accepted a report from it"
            elif clock() >= deadline:
                reason = f"it has been up for {int(keep_seconds // 60)} minutes"
        except Exception:
            log.debug("upgrade: health check for the rollback copy failed", exc_info=True)
        if reason:
            log.info("upgrade: v%s has proven itself (%s) -- the previous build's "
                     "rollback copy is expendable now", config_mod.VERSION, reason)
            try:
                cleanup()
            except Exception:
                log.debug("upgrade: cleanup_old_exe raised", exc_info=True)
            return reason
        try:
            if stop_event.wait(poll_seconds):
                return ""
        except Exception:
            log.debug("upgrade: rollback-copy wait failed", exc_info=True)
            return ""


def revert_to_previous_build(
    state_dir: Path,
    cfg: Any = None,
    *,
    request_shutdown: Optional[Callable[[], None]] = None,
    exe_path: Optional[Path] = None,
    replace_fn: ReplaceFn = os.replace,
    spawn: Optional[SpawnFn] = None,
    clock: Callable[[], float] = time.monotonic,
    sleep_fn: Callable[[float], None] = time.sleep,
    floor_file: Optional[Path] = None,
    now: Optional[float] = None,
) -> tuple[str, str]:
    """Put `<exe>.old` back and launch it. Returns (restored_version, refusal).

    APP-5 / REL-2's automatic rollback, built out of the machinery the
    self-upgrade already has: _rollback for the two renames, _default_spawn
    for the detached hand-off (CCSYNC_REPLACES_PID, the reset _MEI
    environment), the takeover grace for "did the restored build actually
    start". The refusal string is never empty on failure and is logged by the
    caller: "we could not check" must not read as "we rolled back".

    THE FLOOR STILL APPLIES. `previous_version` comes from this machine's own
    start record -- the version that was running when the upgrade happened --
    and a revert below the signed downgrade floor is refused here exactly as a
    dashboard-offered downgrade is, because the floor's whole value is that
    nothing on the machine can lower it (note_floor)."""
    stamp = time.time() if now is None else float(now)
    if not is_frozen() and exe_path is None:
        return "", "this is a source run, so there is no previous build to restore"
    try:
        exe = Path(exe_path) if exe_path is not None else Path(sys.executable)
        old = exe.with_name(exe.name + _OLD_SUFFIX)
        if not old.exists():
            return "", f"there is no rollback copy at {old}"
        previous = str(read_version_state(state_dir).get("previous_version") or "").strip()
        if not previous:
            # An `.old` whose version we cannot name cannot be floor-checked,
            # and a rollback that cannot be floor-checked is not one we may
            # perform automatically.
            return "", ("this machine has no record of which build "
                        f"{old.name} is, so it will not be restored automatically")
        floor = read_floor(Path(floor_file) if floor_file else floor_path(cfg))
        if below_floor(previous, floor):
            return "", (f"v{previous} is below the downgrade floor v{floor} this "
                        f"machine has accepted, so the crash loop needs a human")
        manager = UpgradeManager(
            cfg or {}, replace_fn=replace_fn, spawn_fn=spawn,
            clock_fn=clock, sleep_fn=sleep_fn,
            floor_file=Path(floor_file) if floor_file else floor_path(cfg),
        )
        aside = exe.with_name(new_download_name())
        manager._rollback(old, exe, aside=aside)
        if old.exists():
            return "", (f"the rollback copy could not be moved back over {exe.name} "
                        f"-- it is still at {old}")
        # BEFORE the spawn, both of them: the restored build starts reading
        # these files immediately, and a marker written after it has read them
        # is a marker it never sees.
        _write_json(version_state_path(Path(state_dir)), {
            "version": previous,
            "previous_version": "",
            "starts": 1,
            "first_start_at": stamp,
            "last_clean_shutdown": None,
        })
        note_reverted_from(attempts_path(Path(state_dir)), config_mod.VERSION, now=stamp)
        run = spawn or UpgradeManager._default_spawn
        try:
            child = run(exe)
        except Exception:
            log.exception("upgrade: could not launch the restored build")
            return "", "the restored build could not be launched"
        if child is not None and hasattr(child, "poll"):
            deadline = clock() + CHILD_TAKEOVER_GRACE_SECONDS
            while clock() < deadline:
                code = child.poll()
                if code is not None:
                    return "", (f"the restored build exited with code {code} within "
                                f"{CHILD_TAKEOVER_GRACE_SECONDS:.0f}s of launch")
                sleep_fn(CHILD_TAKEOVER_POLL_SECONDS)
        log.warning(
            "upgrade: v%s has restarted %d times in under %d minutes, so this "
            "machine has restored v%s and is standing down",
            config_mod.VERSION, CRASH_LOOP_STARTS,
            int(CRASH_LOOP_WINDOW_SECONDS // 60), previous,
        )
        if request_shutdown is not None:
            try:
                request_shutdown()
            except Exception:
                log.exception("upgrade: request_shutdown failed after the revert")
        return previous, ""
    except Exception:
        log.exception("upgrade: the crash-loop revert failed")
        return "", "the automatic rollback failed"


def parse_upgrade(resp: Any) -> Optional[dict[str, Any]]:
    """Extract + validate the `upgrade` dict from a report/verify response.

    None for anything unusable, and None when the advertised version equals
    the running one (the server omits the key then, but belt and braces --
    offering a "downgrade" to the version already running would loop)."""
    if not isinstance(resp, dict):
        return None
    info = resp.get("upgrade")
    if not isinstance(info, dict):
        return None
    version = str(info.get("version") or "").strip()
    url = str(info.get("url") or "").strip()
    sha256 = str(info.get("sha256") or "").strip().lower()
    if not version or not url or len(sha256) != 64:
        return None
    if version == config_mod.VERSION:
        return None
    # Carry the SIGNED record fields through verbatim (item 4, 2026-08-17):
    # they are the bytes the release key signed, so anything this function
    # "tidies" would break verification. version/sha256 are the exception --
    # they are normalised above and re-asserted below, which means a server
    # that pads them with whitespace fails verification rather than being
    # quietly accommodated.
    # record_fields, not RECORD_FIELDS: a record carrying the kind-scoped
    # signed extras (requires_dashboard / arch, REL-4 / REL-16, 2026-08-28)
    # is only verifiable with them present -- filtering them out here made
    # every such offer fail its own signature.
    out = {key: info[key]
           for key in release_pubkey.record_fields(info.get("kind"), info)
           if key in info}
    out.update({
        "version": version,
        "url": url,
        "sha256": sha256,
        "size_bytes": info.get("size_bytes"),
        "signature": str(info.get("signature") or "").strip(),
        "pubkey_id": str(info.get("pubkey_id") or "").strip(),
    })
    return out


def advertised_size(info: Any) -> Optional[int]:
    """`size_bytes` as a usable positive int, or None.

    None for anything unusable -- absent (an older dashboard), zero, negative,
    non-numeric, or larger than the hard ceiling. Callers must treat None as
    "unknown size", never as zero: a bogus value must not be able to refuse a
    legitimate update or wave a huge one through. Never raises."""
    try:
        size = int((info or {}).get("size_bytes") or 0)
    except (AttributeError, TypeError, ValueError):
        return None
    if size <= 0 or size > MAX_DOWNLOAD_BYTES:
        return None
    return size


# --------------------------------------------------------------- wording
#
# The offer is "different, not newer" by design (see the module docstring),
# so the SAME machinery advertises an admin rollback and a genuine upgrade.
# Calling both of them "Update available" is what made the tray on this rig
# offer "Update available -> v0.4.3 (install)" while it was running v0.4.5
# (seen live 2026-07-25): one click would have DOWNGRADED the machine and
# reintroduced a whole round of security fixes. The install path is
# unchanged -- only the words, which are the only thing the human has.

_NUMERIC_PART = re.compile(r"^\d+$")

VERSION_NEWER = "newer"
VERSION_OLDER = "older"
VERSION_SAME = "same"
VERSION_UNKNOWN = "unknown"


def parse_version(text: Any) -> Optional[tuple[int, ...]]:
    """A plain dotted-numeric version string as a tuple of ints.

    "0.4.5" -> (0, 4, 5); "v1.2" -> (1, 2). None for ANYTHING else ("",
    "nightly", "0.4.5-hotfix", None), which callers must treat as "ordering
    unknown" and word neutrally.

    Deliberately strict rather than "compare the numeric prefix and ignore
    the rest": truncating "0.4.5-hotfix" to (0, 4) makes it compare OLDER
    than the 0.4.5 it is a hotfix for, and this function's only consumer is
    the sentence that tells an editor whether they are about to upgrade or
    downgrade. Refusing to rank a string we don't fully understand costs a
    neutral label; ranking it wrong costs the wrong click. Never raises."""
    try:
        raw = str(text or "").strip()
        if raw[:1] in ("v", "V"):
            raw = raw[1:]
        parts = raw.split(".")
        if not parts or not all(_NUMERIC_PART.match(part) for part in parts):
            return None
        return tuple(int(part) for part in parts)
    except Exception:
        log.debug("parse_version(%r) failed", text, exc_info=True)
        return None


def compare_to_running(version: Any, running: Optional[str] = None) -> str:
    """"newer" / "older" / "same" / "unknown" for `version` vs the build we
    are running. Never raises -- anything unparseable on either side is
    "unknown", which the labels below render in neutral wording rather than
    guessing a direction."""
    try:
        offered = parse_version(version)
        current = parse_version(config_mod.VERSION if running is None else running)
        if offered is None or current is None:
            return VERSION_UNKNOWN
        if offered > current:
            return VERSION_NEWER
        if offered < current:
            return VERSION_OLDER
        return VERSION_SAME
    except Exception:
        log.debug("compare_to_running(%r) failed", version, exc_info=True)
        return VERSION_UNKNOWN


def offer_label(version: Any, running: Optional[str] = None) -> str:
    """The tray menu item for an available build. The word "update" appears
    ONLY when the offered build really is newer."""
    order = compare_to_running(version, running)
    if order == VERSION_NEWER:
        return f"Update available → v{version} (install)"
    if order == VERSION_OLDER:
        return f"Roll back to v{version} (older build, install)"
    return f"Switch to v{version} (install)"


def offer_toast(version: Any, running: Optional[str] = None) -> str:
    """The tray balloon raised once when a new offer appears (app.py's
    on_available). Same three cases as offer_label."""
    order = compare_to_running(version, running)
    current = config_mod.VERSION if running is None else running
    if order == VERSION_NEWER:
        return f"Update available → v{version}. Use the tray menu to install"
    if order == VERSION_OLDER:
        return (f"Roll back to v{version} offered. That is OLDER than the v{current} "
                f"you are running. Only install it if your admin asked you to.")
    return f"Switch to v{version}. Use the tray menu to install"


def offer_dialog_text(version: Any, running: Optional[str] = None) -> tuple[str, str, str]:
    """(title, body, ok-button label) for the confirmation dialog, so the
    LAST thing shown before the swap agrees with the menu item that opened
    it."""
    order = compare_to_running(version, running)
    current = config_mod.VERSION if running is None else running
    if order == VERSION_OLDER:
        return (
            "CCSYNC.EXE: roll back",
            f"Roll back to v{version}? That is OLDER than the v{current} on this "
            f"machine. You would LOSE whatever v{current} fixed. The companion "
            f"will restart itself.",
            "ROLL BACK",
        )
    if order == VERSION_NEWER:
        return (
            "CCSYNC.EXE: update",
            f"Update to v{version}? The companion will restart itself.",
            "UPDATE",
        )
    return (
        "CCSYNC.EXE: switch build",
        f"Switch to v{version}? You are running v{current}. The companion will "
        f"restart itself.",
        "SWITCH",
    )


class UpgradeManager:
    """Holds the "is an update available" state and performs the swap.

    Thread model: note_report_response() is called from the reporter thread,
    available/apply() from tray-spawned threads -- everything touching
    _available goes through _lock. apply() itself is serialized by the
    _applying flag (a second click while one is in flight is a no-op)."""

    def __init__(
        self,
        cfg: dict[str, Any],
        http_open: Optional[HttpOpenFn] = None,
        replace_fn: ReplaceFn = os.replace,
        spawn_fn: Optional[SpawnFn] = None,
        request_shutdown: Optional[Callable[[], None]] = None,
        on_available: Optional[Callable[[dict[str, Any]], None]] = None,
        clock_fn: Callable[[], float] = time.monotonic,
        sleep_fn: Callable[[float], None] = time.sleep,
        floor_file: Optional[Path] = None,
    ) -> None:
        self.cfg = cfg
        self._http_open = http_open or default_http_open
        self._replace = replace_fn
        self._spawn = spawn_fn or self._default_spawn
        self._request_shutdown = request_shutdown
        self._on_available = on_available
        self._clock = clock_fn
        self._sleep = sleep_fn
        self._lock = threading.Lock()
        self._available: Optional[dict[str, Any]] = None
        self._applying = False
        # Derived, not injected from app.py: app.run() builds this manager
        # BEFORE it computes its state dir, and the floor deliberately lives
        # one level up from state/ anyway (see note_floor).
        self._floor_file = Path(floor_file) if floor_file else floor_path(cfg)
        # One-time migration of a floor written beside a redirected log
        # (comp-app-core-5, 2026-08-21). A no-op on a default install, where
        # both paths are the same file.
        adopt_legacy_floor(cfg, self._floor_file)
        self._transport_note_logged = False
        self._refusal_logged = ""
        # REL-8: WHY the last attempt did not swap, as one of this module's
        # ERROR_* codes. The report carries it so an admin can tell an AV
        # quarantine (sha-mismatch or download-failed on every try) from a
        # wrong-arch binary (exec-failed) from a full disk, none of which
        # looked any different from "hasn't seen the push yet".
        self.last_failure = ""

    def _log_transport_once(self, note: str) -> None:
        if note and not self._transport_note_logged:
            self._transport_note_logged = True
            log.warning("upgrade: %s", note)

    def _accept_offer(self, info: dict[str, Any]) -> tuple[bool, str]:
        """(ok, reason) -- signature, kind/platform, then downgrade floor.
        Never raises.

        Called on EVERY offer as it arrives and again inside
        download_and_verify: the tray must not show "Update available" for a
        build that would be refused at the click, and the download path must
        not depend on having been told about the offer through the tray."""
        try:
            ok, detail = verify_offer(info)
            if not ok:
                return False, f"release signature rejected ({detail})"
            # bug-hunt-2026-09-03 comp-core-1: the signature covers `kind` and
            # `platform` precisely so a Mac cannot be handed a Windows exe and
            # the onboard installer cannot be offered as a companion
            # self-upgrade -- but until now only api._upgrade_info compared
            # them to anything, and the dashboard is the party the offline key
            # was introduced to remove from the trust chain. Both kinds are
            # published into the same table by the same key, so a genuinely
            # signed `onboard` record verified here and was renamed over the
            # running exe. Refused BEFORE note_floor, so a foreign record
            # cannot raise this machine's persisted downgrade floor either.
            # `arch` is deliberately NOT checked (owner decision on comp-core-1,
            # 2026-09-03): release_pubkey.OPTIONAL_KIND_EXTRA_FIELDS states that
            # arch is the DASHBOARD's to enforce, and a client test would refuse
            # every record published before REL-16 added the field.
            kind = str(info.get("kind") or "").strip()
            if kind != "companion":
                return False, (
                    f"the release record for v{info.get('version')} is kind "
                    f"{kind or 'unset'!r}, not a companion build. Only a "
                    f"companion record may be installed over this program"
                )
            offered_platform = str(info.get("platform") or "").strip()
            if offered_platform != platform_key():
                return False, (
                    f"the release record for v{info.get('version')} is for "
                    f"platform {offered_platform or 'unset'!r}, and this machine "
                    f"is {platform_key()!r}"
                )
            # BEFORE note_floor, which is monotonic and persisted
            # (comp-app-core-3, 2026-08-21). A record that says "you may not
            # install below X" while offering X-1 is self-contradictory and
            # can only be a signing-tool or operator slip -- one stale
            # CCSYNC_MIN_VERSION in the environment. Honouring it raised
            # every reporting machine's floor past the build being offered,
            # refused that build and every later one below the typo, and the
            # only way back was deleting upgrade_floor.json BY HAND on each
            # machine: the cost the floor is designed to impose on an
            # attacker, imposed on the fleet by a typo. The floor is raised
            # on RECEIPT of an offer, so this needs no click to bite.
            if _min_version_above_own(info):
                return False, (
                    f"the release record for v{info.get('version')} says it needs "
                    f"v{info.get('min_version')} or newer, which that build is not. "
                    f"The record is malformed and this machine's downgrade floor "
                    f"has NOT been changed"
                )
            floor = note_floor(self._floor_file, info.get("min_version"))
            if below_floor(info.get("version"), floor):
                return False, (
                    f"v{info.get('version')} is below the downgrade floor v{floor} this "
                    f"machine has accepted. Rolling back past the floor is deliberate "
                    f"and manual: delete {self._floor_file} on this machine "
                    f"(docs/RELEASE.md)"
                )
            return True, ""
        except Exception:
            log.debug("upgrade: offer acceptance check failed", exc_info=True)
            return False, "the offer could not be checked"

    def _log_refusal(self, version: Any, reason: str) -> None:
        """One line per distinct (version, reason). The reporter feeds an
        offer every heavy tick, and a refused offer must not write the same
        ERROR to companion.log every 30 seconds forever."""
        key = f"{version}|{reason}"
        if key == self._refusal_logged:
            return
        self._refusal_logged = key
        log.error("upgrade: REFUSING the offered build v%s -- %s", version, reason)

    @property
    def available(self) -> Optional[dict[str, Any]]:
        with self._lock:
            return dict(self._available) if self._available else None

    def note_report_response(self, resp: Any) -> None:
        """Feed a parsed report/verify response. Sets the available state on
        a valid `upgrade` key, CLEARS it when a well-formed response has none
        (the admin rolled current back to our version, or unpublished it).
        Never raises."""
        try:
            info = parse_upgrade(resp)
        except Exception:
            info = None
        if info is not None:
            # An offer that will not be installed is not an offer. Dropping it
            # here (rather than at the click) keeps the tray honest and keeps
            # the "different, not newer" wording from advertising something
            # the machine has already decided to refuse.
            accepted, reason = self._accept_offer(info)
            if not accepted:
                self._log_refusal(info.get("version"), reason)
                info = None
        newly: Optional[dict[str, Any]] = None
        with self._lock:
            if info is not None:
                if self._available is None or self._available["version"] != info["version"]:
                    newly = info
                self._available = info
            elif isinstance(resp, dict):
                self._available = None
        if newly is not None and self._on_available is not None:
            try:
                self._on_available(newly)
            except Exception:
                log.exception("on_available callback failed")

    # -- download ------------------------------------------------------
    def download_and_verify(self, info: dict[str, Any], dest_dir: Path) -> Optional[Path]:
        """Stream the advertised build to dest_dir/<new_download_name()> and
        verify its sha256. Returns the path, or None on any failure (temp file
        removed). Never raises."""
        url = str(info.get("url") or "")
        base = str(self.cfg.get("dashboard_url", "")).strip().rstrip("/")
        # SIGNATURE + FLOOR BEFORE ANYTHING TOUCHES THE NETWORK (item 4,
        # 2026-08-17). Re-checked here even though note_report_response
        # already did it: apply() reads self._available, and this method is
        # public and injectable -- the check that matters must sit on the
        # path that actually writes bytes to disk. The sha256 compared after
        # the download is info["sha256"], i.e. the value the release key
        # signed, so the hash check now proves the file is the SIGNED file
        # rather than merely the file the server described.
        accepted, reason = self._accept_offer(info)
        if not accepted:
            self.last_failure = ERROR_REFUSED
            self._log_refusal(info.get("version"), reason)
            return None
        # ORIGIN PINNING (CORE-M10): an absolute URL is only followed when it
        # points at the same dashboard we already trust for config/tokens.
        if not same_origin(url, base):
            log.error(
                "upgrade: REFUSING an update URL that isn't on the dashboard's own host "
                "(%r vs dashboard_url %r)", url, base,
            )
            self.last_failure = ERROR_REFUSED
            return None
        parsed_url = urllib.parse.urlparse(url)
        if not parsed_url.scheme and not parsed_url.netloc:
            # bug-hunt-2026-09-03 comp-core-5: same_origin waves through ANY
            # relative URL, but only the absolute-path case used to be
            # resolved -- a `url` published without its leading slash reached
            # urllib unresolved and raised "unknown url type", which was filed
            # as ERROR_DOWNLOAD and then counted against REL-8's 8-attempt
            # budget, so a formatting slip in the record looked exactly like an
            # AV quarantine. The leading-slash case keeps its plain
            # concatenation deliberately: a dashboard_url with a path prefix
            # (a reverse proxy mount) must keep that prefix, which urljoin
            # would strip.
            if not base:
                log.warning("upgrade: dashboard_url is not configured -- cannot download")
                self.last_failure = ERROR_REFUSED
                return None
            if url.startswith("/"):
                url = base + url
            else:
                resolved = urllib.parse.urljoin(base + "/", url)
                if not same_origin(resolved, base):
                    log.error(
                        "upgrade: REFUSING a relative update URL that resolves off the "
                        "dashboard's own host (%r against %r -> %r)", url, base, resolved,
                    )
                    self.last_failure = ERROR_REFUSED
                    return None
                log.info(
                    "upgrade: the offered URL %r is relative -- resolved against "
                    "dashboard_url as %r", url, resolved,
                )
                url = resolved
        # TRANSPORT (item 4): checked after the origin is resolved, because
        # "which scheme and host will this actually hit" is only settled here.
        ok_transport, note = transport_ok(base)
        if not ok_transport:
            self.last_failure = ERROR_REFUSED
            self._log_refusal(info.get("version"), note)
            return None
        self._log_transport_once(note)
        headers = {}
        token = str(self.cfg.get("dashboard_token", "")).strip()
        if token:
            headers["X-CCSync-Token"] = token

        # The dashboard publishes size_bytes as the byte count it actually
        # wrote (api.py's publish handler), and it was parsed by parse_upgrade
        # and then read by nothing: neither the flat 200 MB free-space margin
        # nor the download ceiling consulted it. A 250 MB build downloaded
        # onto 210 MB of free space still passed the check and only failed at
        # the last write.
        advertised = advertised_size(info)

        try:
            free = shutil.disk_usage(str(dest_dir)).free
            needed = MIN_FREE_BYTES_MARGIN + (advertised or 0)
            if free < needed:
                log.warning(
                    "upgrade: %.0f MB free at %s but the update needs %.0f MB "
                    "(+ margin) -- refusing to download it",
                    free / 1_000_000, dest_dir, needed / 1_000_000,
                )
                self.last_failure = ERROR_SPACE
                return None
        except Exception:
            log.debug("upgrade: free-space check failed; continuing", exc_info=True)

        # The advertised size is the tighter of the two ceilings whenever the
        # server gave us one: a body that outgrows it is not the build we were
        # offered, and there is no reason to write the rest of it to disk.
        ceiling = min(MAX_DOWNLOAD_BYTES, advertised) if advertised else MAX_DOWNLOAD_BYTES

        tmp = dest_dir / new_download_name()
        digest = hashlib.sha256()
        written = 0
        try:
            with self._http_open(url, headers, DOWNLOAD_TIMEOUT) as resp:
                status = redirect_status(resp)
                if status is not None:
                    raise _RedirectRefused(status)
                with tmp.open("wb") as fh:
                    while True:
                        chunk = resp.read(256 * 1024)
                        if not chunk:
                            break
                        written += len(chunk)
                        if written > ceiling:
                            raise ValueError(
                                f"update exceeded the "
                                f"{ceiling // (1024 * 1024)} MB ceiling"
                            )
                        fh.write(chunk)
                        digest.update(chunk)
        except Exception as exc:
            code = getattr(exc, "code", None)
            try:
                is_redirect = isinstance(exc, _RedirectRefused) or (
                    isinstance(exc, urllib.error.HTTPError) and 300 <= int(code) < 400
                )
            except (TypeError, ValueError):
                # Nothing in this handler may raise: it runs on the path where
                # the running exe is about to be renamed.
                is_redirect = False
            if is_redirect:
                # NOT followed, deliberately -- see build_no_redirect_opener.
                # The origin check above is worthless if a redirect can move
                # the download (and the X-CCSync-Token header) elsewhere
                # afterwards (AUDIT_3 H-1).
                log.error(
                    "upgrade: REFUSING the update download -- %s answered with a "
                    "redirect (HTTP %s). The update must be served by the dashboard "
                    "itself; nothing was downloaded and no token was re-sent.",
                    url, code or "3xx",
                )
            else:
                log.warning("upgrade: download failed: %s", exc)
            self.last_failure = ERROR_DOWNLOAD
            self._unlink_quietly(tmp)
            return None
        if digest.hexdigest() != info.get("sha256"):
            log.warning("upgrade: sha256 mismatch on downloaded build -- discarding it")
            self.last_failure = ERROR_SHA
            self._unlink_quietly(tmp)
            return None
        self._make_executable(tmp)
        return tmp

    @staticmethod
    def _make_executable(path: Path) -> None:
        """Give the verified download the execute bit on POSIX.

        A file created by open("wb") is 0644 under the usual umask, and macOS
        will not exec it -- so the swap would rename a non-executable file
        over the companion and the respawn would fail with EACCES. Windows has
        no execute bit and os.chmod there only toggles read-only, so it is
        never called on win32.

        AFTER the sha256 check, deliberately: an unverified download must
        never be made runnable, however briefly. os.replace preserves the
        mode, so setting it here carries through both renames to the installed
        path -- no chmod is needed once the binary is in place.

        Never raises, and a failure does NOT abort the upgrade: chmod can be a
        no-op-with-EPERM on exotic mounts where the file is already executable,
        and refusing a working update over that would be worse than the
        alternative -- if the file really cannot be executed, _apply_inner's
        spawn fails and rolls the whole swap back."""
        if sys.platform == "win32":
            return
        try:
            os.chmod(path, 0o755)
        except OSError as exc:
            log.warning(
                "upgrade: could not set the execute bit on %s (%s) -- continuing; "
                "if the new build cannot start, the swap rolls back", path, exc,
            )

    # -- the swap ------------------------------------------------------
    def apply(self) -> bool:
        """Download + swap + restart. Never raises; False means "nothing
        happened / rolled back, the current build keeps running"."""
        info = self.available
        if info is None:
            return False
        if not is_frozen():
            log.info("upgrade: not a frozen exe (source run) -- self-upgrade skipped")
            return False
        with self._lock:
            if self._applying:
                return False
            self._applying = True
        try:
            return self._apply_inner(info)
        finally:
            with self._lock:
                self._applying = False

    def _apply_inner(self, info: dict[str, Any]) -> bool:
        exe = Path(sys.executable)
        # Cleared here, not on success: every return below this line either
        # sets a code or is the swap going through (REL-8).
        self.last_failure = ""
        new = self.download_and_verify(info, exe.parent)
        if new is None:
            return False

        old = exe.with_name(exe.name + _OLD_SUFFIX)
        # `except Exception` throughout: _replace is injectable and os.replace
        # is not limited to OSError (CORE-H7). Anything escaping here kills
        # the tray daemon thread while the exe may not exist.
        try:
            self._replace(exe, old)
        except Exception as exc:
            log.warning("upgrade: could not move the running exe aside: %s", exc)
            self.last_failure = ERROR_SWAP
            self._unlink_quietly(new)
            return False
        try:
            self._replace(new, exe)
        except Exception as exc:
            log.warning("upgrade: could not move the new exe into place: %s -- rolling back", exc)
            self.last_failure = ERROR_SWAP
            self._rollback(old, exe, aside=None)
            # The new build is still parked at the .new download and we are not going
            # to run it -- don't leave 20 MB behind.
            self._unlink_quietly(new)
            return False
        try:
            child = self._spawn(exe)
        except Exception as exc:
            log.warning("upgrade: could not launch the new build: %s -- rolling back", exc)
            self.last_failure = ERROR_EXEC
            self._rollback(old, exe, aside=new)
            return False

        # R11 belt-and-braces: don't stand down until the child has survived
        # its own startup. Its single-instance guard now waits out our mutex,
        # so an exit inside the grace window is a startup failure, not a lost
        # race -- roll back and keep running rather than leave the machine
        # with nothing. Only enforceable when the spawn seam hands back
        # something poll()-able: _default_spawn does; injected spawns that
        # return None keep the fire-and-forget contract.
        if child is not None and hasattr(child, "poll"):
            deadline = self._clock() + CHILD_TAKEOVER_GRACE_SECONDS
            while self._clock() < deadline:
                code = child.poll()
                if code is not None:
                    log.warning(
                        "upgrade: the new build exited with code %s within %.0fs of "
                        "launch -- rolling back rather than standing down",
                        code, CHILD_TAKEOVER_GRACE_SECONDS,
                    )
                    self.last_failure = ERROR_EXEC
                    self._rollback(old, exe, aside=new)
                    return False
                self._sleep(CHILD_TAKEOVER_POLL_SECONDS)

        log.info("upgrade: v%s launched; shutting down v%s", info["version"], config_mod.VERSION)
        if self._request_shutdown is not None:
            try:
                self._request_shutdown()
            except Exception:
                log.exception("upgrade: request_shutdown failed (exit manually)")
        return True

    def _rollback(self, old: Path, exe: Path, aside: Optional[Path]) -> None:
        """Restore `old` to `exe`; if the failed new build currently sits at
        `exe`, park it back at `aside` first so the restore can land.

        `except Exception`, not `except OSError`: `_replace` is an injectable
        callable and os.replace can raise TypeError/ValueError (surrogate
        path) or anything a wrapper raises. A raise here escaped
        _apply_inner -> apply() -> app.apply_upgrade() -> the tray's dialog
        handler, killing the tray daemon thread to invisible stderr WHILE
        `exe` did not exist -- renamed to `.old`, with the new build parked
        at the `.new` download (AUDIT_2 CORE-H7). Rollback is the last line of
        defence; it may not have a failure mode of its own."""
        restored = False
        try:
            if aside is not None:
                self._replace(exe, aside)
            self._replace(old, exe)
            restored = True
        except Exception:
            log.exception(
                "upgrade: ROLLBACK FAILED -- the previous build is at %s; "
                "rename it back to %s by hand", old, exe.name,
            )
        if not restored:
            return
        log.info("upgrade: rolled back to the previous build at %s", exe)
        # The rollback SUCCEEDED, so `aside` now holds ~20 MB of a build we
        # just refused to run. It was never unlinked (AUDIT_2 CORE-H7) and
        # would be silently truncated by the next apply()'s "wb" open.
        if aside is not None:
            self._unlink_quietly(aside)

    @staticmethod
    def _unlink_quietly(path: Path) -> None:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass

    @staticmethod
    def _default_spawn(exe: Path) -> Any:
        # DETACHED_PROCESS decouples from this soon-dead process;
        # CREATE_NO_WINDOW stops Windows allocating a fresh (empty, killable)
        # console if the exe is ever a console build again -- closing that
        # mystery window kills the companion (seen live 2026-07-25). All std
        # handles to DEVNULL; build.spec is console=False since 0.3.2.
        detach: dict[str, Any] = {}
        if sys.platform == "win32":
            detach["creationflags"] = (
                subprocess.DETACHED_PROCESS
                | subprocess.CREATE_NEW_PROCESS_GROUP
                | subprocess.CREATE_NO_WINDOW
            )
        else:
            # POSIX has no creationflags at all (passing one raises), so the
            # detach is start_new_session=True: setsid() gives the child its
            # own session and process group, so it outlives this process and
            # never takes a signal aimed at the dying parent's group. This
            # matters more on macOS than on Windows -- the LaunchAgent is
            # RunAtLoad-only with no KeepAlive, so nothing else will ever
            # bring the new build up if this spawn dies with us.
            detach["start_new_session"] = True
        # CRITICAL for onefile self-restart on EVERY platform: without this,
        # PyInstaller >=6 has the spawned copy REUSE this process's _MEI dir --
        # which our bootloader deletes on exit moments later, leaving the
        # new instance running from a vanished directory (broken tkinter,
        # broken lazy imports, or an outright Tcl crash at startup -- all
        # three seen live 2026-07-25). PYINSTALLER_RESET_ENVIRONMENT makes
        # the child a fully independent instance with its own extraction.
        env = {
            k: v for k, v in os.environ.items()
            if not k.startswith("_PYI") and not k.startswith("_MEI")
        }
        # Same reasoning one level up: resolve_bridge pins PYTHONHOME/
        # PYTHON3HOME at THIS process's _MEI... dir so fusionscript.dll loads
        # our python3.dll. The bootloader deletes that dir seconds from now,
        # so inheriting them points the new instance's Python at a vanished
        # directory (AUDIT_2 CORE-M6).
        from . import resolve_bridge

        env = resolve_bridge.sanitized_child_env(env)
        env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
        # The new build is launched BEFORE this one exits -- it has to be, or
        # a failed launch could not roll the swap back -- so for a second or
        # two there really are two companions, and the single-instance guard
        # is entitled to refuse the newcomer. The dying predecessor holds the
        # slot for exactly as long as its lanes take to stop, on BOTH
        # platforms: posix's guard is a pid file with a liveness check, and
        # the win32 named mutex lives until our last handle closes at exit
        # (R11 -- "released the instant we die, the child wins by timing" was
        # backwards, and cost an editor machine its companion 2026-08-12).
        # This tells the child WHOSE pid it may wait for
        # (app._acquire_lock_file / app._acquire_mutex_win32). Set on every
        # platform: harmless where it is not needed, and one less thing to be
        # platform-conditional about.
        env["CCSYNC_REPLACES_PID"] = str(os.getpid())
        # Returned so _apply_inner can watch the hand-off: a child that dies
        # within the grace window rolls the swap back instead of the parent
        # standing down over a corpse.
        return subprocess.Popen(
            [str(exe)],
            cwd=str(exe.parent),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            env=env,
            **detach,
        )


def restart_self(
    request_shutdown: Callable[[], None],
    spawn: Optional[Callable[..., Any]] = None,
    clock: Callable[[], float] = time.monotonic,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> bool:
    """Relaunch THIS build and shut the current instance down. Never raises.

    The self-upgrade's spawn/hand-off machinery (mutex wait keyed on
    CCSYNC_REPLACES_PID, PYINSTALLER_RESET_ENVIRONMENT, the R11 takeover
    grace) without the download/swap: used by app._maybe_recover_stale_bridge
    to shed a stale fusionscript client after the Resolve it was connected to
    exits -- left in place, that client can wedge the NEXT Resolve's
    scripting server for every client on the machine (proven live
    2026-08-12).

    False = nothing happened and the current instance keeps running: a source
    run (nothing to relaunch; restart it by hand), a failed spawn, or a
    replacement that died inside the takeover grace window.
    """
    if not is_frozen():
        log.info("self-restart: source run -- restart the companion by hand "
                 "to refresh its Resolve link")
        return False
    exe = Path(sys.executable)
    run = spawn or UpgradeManager._default_spawn
    try:
        child = run(exe)
    except Exception:
        log.exception("self-restart: could not launch the replacement")
        return False
    if child is not None and hasattr(child, "poll"):
        deadline = clock() + CHILD_TAKEOVER_GRACE_SECONDS
        while clock() < deadline:
            code = child.poll()
            if code is not None:
                log.warning(
                    "self-restart: the replacement exited with code %s within "
                    "%.0fs -- keeping this instance running",
                    code, CHILD_TAKEOVER_GRACE_SECONDS,
                )
                return False
            sleep_fn(CHILD_TAKEOVER_POLL_SECONDS)
    log.info("self-restart: replacement launched; shutting this instance down")
    try:
        request_shutdown()
    except Exception:
        log.exception("self-restart: request_shutdown failed (exit manually)")
    return True
