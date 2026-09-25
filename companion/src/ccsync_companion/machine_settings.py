"""Fleet-jobs settings asked for from the dashboard's account page.

Account page 2026-09-25 (docs/ACCOUNT_PAGE_FEATURES.md sections 4 and 5).
The owner of a computer, or an admin, may ask it from the dashboard to change
`jobs_enabled` and `jobs_kinds` - the two settings that until now could only
be changed at the tray (Settings, FLEET JOBS). The dashboard puts the ask on
every report reply as `commands.machine_settings` until this computer
answers; this module applies it to config.toml and keeps the answer.

Constraints that shape it:

- **Wired or remote is never requestable** (CR-88). `mode` is not in ACCEPTS
  and a request that names it, or any other key this build does not take, is
  refused WHOLE: applying half of a request the dashboard thinks it sent in
  one piece would leave the page saying something this computer never did.
- **The command is standing.** It rides every reply until the answer lands,
  so applying it must be idempotent: the ledger answers a redelivered id from
  disk and writes nothing. A `failed` write (config.toml could not be saved)
  is retried only after FAILED_RETRY_SECONDS, so a disk that refuses every
  write is not rewritten every 30 seconds.
- **Nothing takes effect until CCSync next starts** (owner decision D-8):
  every `jobs_*` key is read at construction (jobs_runner, capabilities), so
  the write goes to config.toml exactly as the tray's own control does, and
  the report's `pending_restart` says which values on disk differ from the
  running ones. Nothing here restarts anything.
- **`jobs_kinds = ""` is EVERY kind** (capabilities.job_kinds). A non-empty
  list that names only kinds this build does not know would be read as `[]`,
  every kind, the opposite of what was asked, so it is refused rather than
  written.
- **Nothing secret goes on the wire.** The YouTube part is four status words;
  the cookie health record's `reason` is yt-dlp's own text and stays here,
  as do the cookies and their path.

Never raises out of its public functions: they run on the reporter thread.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Optional

from . import config as config_mod

log = logging.getLogger("ccsync.machine_settings")

ACCEPTS = ("jobs_enabled", "jobs_kinds")
REPORTED_RESTART_KEYS = ("jobs_enabled", "jobs_kinds",
                         "jobs_volunteer_minutes", "drive_reminder_minutes")
LEDGER_NAME = "machine_settings_request.json"      # under the state dir (~/.ccsync/state)
FAILED_RETRY_SECONDS = 300

STATE_APPLIED = "applied"
STATE_REFUSED = "refused"
STATE_FAILED = "failed"

# The ledger keeps the last few answers by id, not only the last one: a reply
# that is delivered late (a merged newer ask on the dashboard, then the older
# id redelivered by a proxy retry) must still be answered from disk rather
# than applied a second time over the newer values.
_LEDGER_KEEP = 16
_ID_MAX_CHARS = 64
_DETAIL_MAX_CHARS = 255     # the dashboard's MachineSettingsAppliedIn cap

_DEFAULT_VOLUNTEER_MINUTES = 30
_DEFAULT_REMINDER_MINUTES = 30.0

# One request applied at a time: the reporter thread is the only caller in
# the running app, but an off-cycle report shares it and a test may not.
_apply_lock = threading.Lock()

# config.toml as read from disk, re-read only when its mtime/size change:
# report_section runs on every report tick, light ones included.
_disk_lock = threading.Lock()
_disk_cache: Optional[tuple[str, int, int, dict[str, Any]]] = None

# Every answer this process has given, by ledger path, kept beside the file
# (account page 2026-09-25, review round): a ledger that cannot be written
# (full disk, a locked state dir) must not make a redelivered id look new -
# that rewrote config.toml and fired the balloon on every report cycle, and
# with no `applied` in the report the dashboard kept re-sending the command
# for its whole 14-day life. The file is still what survives a restart.
_mem_lock = threading.Lock()
_mem_answers: dict[str, dict[str, Any]] = {}


# -- small helpers ------------------------------------------------------------


def _iso(now: float) -> str:
    try:
        return datetime.fromtimestamp(float(now), tz=timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ")
    except (TypeError, ValueError, OverflowError, OSError):
        return ""


def _parse_iso(text: Any) -> Optional[float]:
    try:
        raw = str(text or "").strip()
        if not raw:
            return None
        return datetime.strptime(raw, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc).timestamp()
    except (TypeError, ValueError):
        return None


def _known_kinds() -> tuple[str, ...]:
    from . import capabilities as capabilities_mod

    return tuple(getattr(capabilities_mod, "KNOWN_KINDS", ()) or ())


def _kind_label(kind: str) -> str:
    """The settings window's labels, so the balloon and the window name a
    kind the same way. Deferred: settings_window imports the tray."""
    try:
        from . import settings_window

        return settings_window._kind_label(kind)
    except Exception:
        return kind


def _answer(request_id: str, state: str, detail: str, now: float) -> dict[str, Any]:
    return {"id": request_id, "state": state,
            "detail": str(detail or "")[:_DETAIL_MAX_CHARS], "at": _iso(now)}


# -- the ledger ---------------------------------------------------------------


def _read_ledger(ledger_path: Path) -> dict[str, Any]:
    try:
        data = json.loads(Path(ledger_path).read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {"last": None, "answers": {}}
    if not isinstance(data, dict):
        return {"last": None, "answers": {}}
    answers = data.get("answers")
    if not isinstance(answers, dict):
        answers = {}
    last = data.get("last")
    return {"last": last if isinstance(last, dict) else None,
            "answers": {str(k): v for k, v in answers.items() if isinstance(v, dict)}}


def _write_ledger(ledger_path: Path, ledger: dict[str, Any]) -> bool:
    """tmp + os.replace: a half-written ledger would forget an applied id,
    and a forgotten id is a request applied twice."""
    path = Path(ledger_path)
    tmp = path.with_name(path.name + ".tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(json.dumps(ledger, sort_keys=True), encoding="utf-8")
        os.replace(tmp, path)
        return True
    except OSError:
        log.exception("machine settings: could not write %s", path)
        try:
            tmp.unlink()
        except OSError:
            pass
        return False


def _bounded(answers: Mapping[str, Any], answer: dict[str, Any]) -> dict[str, Any]:
    out = dict(answers or {})
    out.pop(answer["id"], None)
    out[answer["id"]] = answer
    # Oldest first by insertion; keep the newest few.
    while len(out) > _LEDGER_KEEP:
        out.pop(next(iter(out)))
    return out


def _mem_ledger(ledger_path: Path) -> Optional[dict[str, Any]]:
    with _mem_lock:
        found = _mem_answers.get(str(Path(ledger_path)))
        if found is None:
            return None
        return {"last": found["last"], "answers": dict(found["answers"])}


def _forget_memory() -> None:
    """Tests: stand in for a restart of CCSync."""
    with _mem_lock:
        _mem_answers.clear()


def _record(ledger_path: Path, answer: dict[str, Any]) -> bool:
    """Keep the answer in memory first, then on disk. -> whether the disk
    write succeeded (the in-memory copy answers redeliveries either way)."""
    key = str(Path(ledger_path))
    with _mem_lock:
        held = _mem_answers.get(key) or {"last": None, "answers": {}}
        _mem_answers[key] = {"last": answer,
                             "answers": _bounded(held["answers"], answer)}
    ledger = _read_ledger(ledger_path)
    return _write_ledger(ledger_path, {
        "last": answer, "answers": _bounded(ledger.get("answers") or {}, answer)})


def last_answer(ledger_path: Path) -> Optional[dict[str, Any]]:
    """The ledger's last answer, or None. Never raises. This process's own
    last answer wins over the file: every answer goes to memory before the
    file, so memory is never the older of the two, and it is the only copy
    when the file write failed."""
    try:
        held = _mem_ledger(ledger_path)
        if held is not None and isinstance(held.get("last"), dict):
            return dict(held["last"])
        last = _read_ledger(ledger_path).get("last")
        return dict(last) if isinstance(last, dict) else None
    except Exception:
        return None


def answer_for(ledger_path: Path, request_id: str) -> Optional[dict[str, Any]]:
    """The recorded answer to one id, or None. Never raises."""
    try:
        held = _mem_ledger(ledger_path)
        found = held["answers"].get(str(request_id)) if held is not None else None
        if not isinstance(found, dict):
            found = _read_ledger(ledger_path)["answers"].get(str(request_id))
        return dict(found) if isinstance(found, dict) else None
    except Exception:
        return None


# -- applying -----------------------------------------------------------------


def _validate(settings: Mapping[str, Any]) -> tuple[Optional[str], dict[str, Any]]:
    """-> (refusal sentence or None, {key: value to write})."""
    for key in settings:
        if key not in ACCEPTS:
            return f"this computer does not take {key} from the dashboard", {}
    if not settings:
        return "the request named nothing to change", {}
    writes: dict[str, Any] = {}
    if "jobs_enabled" in settings:
        value = settings["jobs_enabled"]
        if not isinstance(value, bool):
            return "jobs_enabled must be true or false", {}
        writes["jobs_enabled"] = value
    if "jobs_kinds" in settings:
        raw = settings["jobs_kinds"]
        if not isinstance(raw, list) or not all(isinstance(k, str) for k in raw):
            return "jobs_kinds must be a list of kinds of work", {}
        known = _known_kinds()
        kept: list[str] = []
        for name in raw:
            name = name.strip()
            if name in known and name not in kept:
                kept.append(name)
        if raw and not kept:
            return "this computer does not know those kinds of work", {}
        # The settings window's own encoding (_fleet_jobs_controls): all of
        # them is "", so a build that learns a new kind later does not find
        # this computer excluded from it by a list nobody knew they wrote.
        if not kept or set(kept) == set(known):
            writes["jobs_kinds"] = ""
        else:
            # Known-kinds order, the order the window writes them in.
            writes["jobs_kinds"] = ", ".join(k for k in known if k in kept)
    return None, writes


def apply_request(command: Mapping[str, Any], *, config_path: Path,
                  ledger_path: Path, now: float) -> dict[str, Any]:
    """Apply one `commands.machine_settings` -> {"id","state","detail","at"}.

    Returns {} for a malformed command (logged, answered with nothing: there
    is no id to answer). Never raises."""
    try:
        if not isinstance(command, Mapping):
            log.warning("machine settings: ignoring a command that is not an object")
            return {}
        request_id = command.get("id")
        settings = command.get("set")
        if (not isinstance(request_id, str) or not request_id.strip()
                or len(request_id) > _ID_MAX_CHARS or not isinstance(settings, Mapping)):
            log.warning("machine settings: ignoring a malformed command (id %r)",
                        str(request_id)[:_ID_MAX_CHARS] if request_id is not None else None)
            return {}
        with _apply_lock:
            prior = answer_for(ledger_path, request_id)
            if prior is not None:
                state = str(prior.get("state") or "")
                if state in (STATE_APPLIED, STATE_REFUSED):
                    return prior
                if state == STATE_FAILED:
                    at = _parse_iso(prior.get("at"))
                    if at is not None and 0 <= now - at < FAILED_RETRY_SECONDS:
                        return prior
            refusal, writes = _validate(settings)
            if refusal is not None:
                answer = _answer(request_id, STATE_REFUSED, refusal, now)
                _record(ledger_path, answer)
                return answer
            ok = True
            for key, value in writes.items():
                try:
                    if not config_mod.set_value(Path(config_path), key, value):
                        ok = False
                except Exception:
                    log.exception("machine settings: could not write %s", key)
                    ok = False
                if not ok:
                    break
            if ok:
                answer = _answer(request_id, STATE_APPLIED, "", now)
            else:
                answer = _answer(request_id, STATE_FAILED, "could not save config.toml", now)
            _forget_disk_cache()
            if not _record(ledger_path, answer):
                # Answered from memory until CCSync restarts; after that a
                # redelivered id is applied once more (the same values, so
                # the file ends the same) and balloons once more.
                log.warning("machine settings: answer %s kept in memory only",
                            answer["state"])
            return answer
    except Exception:
        log.exception("machine settings: could not apply the dashboard's request")
        return {}


# -- the report section -------------------------------------------------------


def _forget_disk_cache() -> None:
    global _disk_cache
    with _disk_lock:
        _disk_cache = None


def _config_on_disk(path: Path) -> Optional[dict[str, Any]]:
    """config.toml as the next start will read it, cached by mtime + size;
    None when this computer cannot tell what the next start will read.

    load_config never raises on a broken file: invalid TOML with no backup
    comes back as ALL DEFAULTS with `_config_load_error` set (account page
    2026-09-25, review round). Comparing those defaults with the running
    values reported a change nobody asked for ("take every kind, enabled")
    as saved and waiting for a restart. A copy rescued from config.toml.bak
    is real settings, just possibly stale, and is what the next start would
    run on too, so it is still compared."""
    global _disk_cache
    path = Path(path)
    try:
        st = path.stat()
        key = (str(path), int(st.st_mtime_ns), int(st.st_size))
    except OSError:
        key = None
    with _disk_lock:
        if key is not None and _disk_cache is not None and _disk_cache[:3] == key:
            return _disk_cache[3]
    data = dict(config_mod.load_config(path) or {})
    if data.get("_config_load_error") and not data.get("_config_from_backup"):
        # Not cached: the next tick asks again.
        return None
    if key is not None:
        with _disk_lock:
            _disk_cache = (key[0], key[1], key[2], data)
    return data


def _volunteer_minutes(cfg: Mapping[str, Any]) -> int:
    # settings_window._volunteer_minutes' coercion, repeated so this module
    # does not pull the tray in on every report.
    try:
        value = int(float(cfg.get("jobs_volunteer_minutes", _DEFAULT_VOLUNTEER_MINUTES)
                          or _DEFAULT_VOLUNTEER_MINUTES))
    except (TypeError, ValueError, OverflowError):
        value = _DEFAULT_VOLUNTEER_MINUTES
    return value if value > 0 else _DEFAULT_VOLUNTEER_MINUTES


def _reminder_minutes(cfg: Mapping[str, Any]) -> float:
    # validate_config / drive_reminder.interval_seconds: a number >= 0, 0 =
    # first warning only, anything else is the default.
    default = float(config_mod.DEFAULTS.get("drive_reminder_minutes",
                                            _DEFAULT_REMINDER_MINUTES))
    raw = cfg.get("drive_reminder_minutes", default)
    if isinstance(raw, bool):
        return default
    try:
        value = float(raw)
    except (TypeError, ValueError, OverflowError):
        return default
    if value != value or value < 0 or value == float("inf"):
        return default
    return value


# capabilities.job_kinds logs a warning for every unknown name it drops, and
# this runs on every report: remember the answer per raw value.
_kinds_cache: dict[str, list[str]] = {}


def _job_kinds(cfg: Mapping[str, Any]) -> list[str]:
    raw = cfg.get("jobs_kinds", None)
    key = repr(raw)
    cached = _kinds_cache.get(key)
    if cached is not None:
        return list(cached)
    from . import capabilities as capabilities_mod

    value = list(capabilities_mod.job_kinds(dict(cfg)))
    if len(_kinds_cache) > 32:
        _kinds_cache.clear()
    _kinds_cache[key] = value
    return list(value)


def _same_value(key: str, on_disk: Any, running: Any) -> bool:
    # Kinds are a SET: a hand-written "peaks, whisper" and the
    # "whisper, peaks" this module writes are the same work, and an order
    # difference must not read as a change waiting for a restart (account
    # page 2026-09-25, review round). The on-disk list is still what is
    # reported when the sets do differ.
    if key == "jobs_kinds":
        return set(on_disk or ()) == set(running or ())
    return on_disk == running


def _normalised(cfg: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "jobs_enabled": bool(cfg.get("jobs_enabled", True)),
        "jobs_kinds": _job_kinds(cfg),
        "jobs_volunteer_minutes": _volunteer_minutes(cfg),
        "drive_reminder_minutes": _reminder_minutes(cfg),
    }


def _youtube(app: Any, cfg: Mapping[str, Any]) -> Optional[dict[str, Any]]:
    """Four status words, or None when the SITE has YouTube downloads off
    (4.3: omitted then). Gated on the site's own switch rather than
    ytdlp_manager.youtube_enabled, which also folds in this machine's
    opt-out: `downloads` IS that opt-out, and gating on it would make the
    field always true."""
    from . import site as site_mod
    from . import ytdlp_manager

    if not site_mod.feature_enabled("youtube_download"):
        return None
    downloads = bool(ytdlp_manager.youtube_enabled(dict(cfg)))
    signin_enabled = bool(downloads and ytdlp_manager.unblock_enabled())
    try:
        from . import tray as tray_mod

        terms = bool(tray_mod._ytdl_attested(app))
    except Exception:
        log.debug("machine settings: attestation unreadable", exc_info=True)
        terms = False
    signin = "none"
    if signin_enabled:
        try:
            from . import ytdl_cookies

            # The status word only. The record's `reason` is yt-dlp's own
            # text and never leaves this machine; nor do the cookies.
            signin = str((ytdl_cookies.health(dict(cfg)) or {}).get("status") or "none")[:16]
        except Exception:
            log.debug("machine settings: cookie health unreadable", exc_info=True)
            signin = "none"
    return {"downloads": downloads, "signin_enabled": signin_enabled,
            "terms_accepted": terms, "signin": signin}


def _state_dir_of(app: Any) -> Optional[Path]:
    state_dir = getattr(app, "_state_dir", None)
    if state_dir:
        return Path(state_dir)
    try:
        return config_mod.resolved_log_path(getattr(app, "config", {}) or {}).parent / "state"
    except Exception:
        return None


def ledger_path_of(app: Any) -> Optional[Path]:
    state_dir = _state_dir_of(app)
    return None if state_dir is None else state_dir / LEDGER_NAME


def report_section(app: Any) -> dict[str, Any]:
    """Section 4.3's `machine_settings`. {} on failure (the reporter omits
    it). Never raises."""
    try:
        running_cfg = dict(getattr(app, "config", {}) or {})
        running = _normalised(running_cfg)
        section: dict[str, Any] = {
            "accepts": list(ACCEPTS),
            "jobs_volunteer_minutes": running["jobs_volunteer_minutes"],
            "drive_reminder_minutes": running["drive_reminder_minutes"],
        }
        try:
            youtube = _youtube(app, running_cfg)
        except Exception:
            log.debug("machine settings: youtube state unreadable", exc_info=True)
            youtube = None
        if youtube is not None:
            section["youtube"] = youtube
        # Left OUT, not sent as {}, when config.toml cannot be read or does
        # not parse: {} is a positive "nothing is waiting", which the page
        # shows as "In effect." when this computer cannot tell (account page
        # 2026-09-25, review round). The rest of the section still goes.
        pending: Optional[dict[str, Any]] = {}
        try:
            disk_cfg = _config_on_disk(config_mod.CONFIG_PATH)
            if disk_cfg is None:
                pending = None
            else:
                on_disk = _normalised(disk_cfg)
                for key in REPORTED_RESTART_KEYS:
                    if not _same_value(key, on_disk[key], running[key]):
                        pending[key] = on_disk[key]
        except Exception:
            log.debug("machine settings: config.toml unreadable", exc_info=True)
            pending = None
        if pending is not None:
            section["pending_restart"] = pending
        ledger = ledger_path_of(app)
        if ledger is not None:
            last = last_answer(ledger)
            if last and last.get("id"):
                section["applied"] = {
                    "id": str(last.get("id") or "")[:_ID_MAX_CHARS],
                    "state": str(last.get("state") or "")[:32],
                    "detail": str(last.get("detail") or "")[:_DETAIL_MAX_CHARS],
                    "at": str(last.get("at") or "")[:64],
                }
        return section
    except Exception:
        log.exception("machine settings: could not build the report section")
        return {}


# -- the balloon --------------------------------------------------------------


def change_sentence(applied_settings: Mapping[str, Any], by: str) -> str:
    """The tray balloon for a request this computer has just applied. Plain
    words, no em dash (the owner's rule for visible text)."""
    who = str(by or "").strip() or "Your administrator"
    later = "It takes effect the next time CCSync starts."
    settings = applied_settings if isinstance(applied_settings, Mapping) else {}
    parts: list[str] = []
    enabled = settings.get("jobs_enabled")
    if enabled is False:
        parts.append("stop taking fleet work")
    elif enabled is True:
        parts.append("take fleet work again")
    if "jobs_kinds" in settings:
        kinds = settings.get("jobs_kinds")
        known = _known_kinds()
        names = [k for k in known if isinstance(kinds, list) and k in kinds]
        if not names or set(names) == set(known):
            parts.append("take every kind of fleet work")
        else:
            parts.append("take only these kinds of fleet work: "
                         + ", ".join(_kind_label(k) for k in names))
    if not parts:
        return f"{who} changed this computer's fleet work settings. {later}"
    return f"{who} asked this computer to {' and '.join(parts)}. {later}"
