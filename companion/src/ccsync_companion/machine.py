"""This computer's identity — the one thing about it that survives a rename.

Added 2026-08-18 for docs/MULTI_MACHINE_PLAN.md WP1: a person can own more
than one editing machine, and each needs its own sync plan. The dashboard
keys that plan on `(editor_username, machine)` where `machine` is
`platform.node()` — the hostname — because that is the key every other
per-machine table in the fleet already uses.

A hostname is a LABEL, though: an editor can change it in Windows in ten
seconds, and on the far side that reads as a brand-new computer with an empty
plan, i.e. a machine that silently stops syncing. So the companion mints an
id of its own, once, and reports it alongside the hostname; the dashboard
carries the plan across when it sees a known id under a new name.

What this is NOT:

  * NOT a credential. Nothing is authorised by it. It rides inside the same
    authenticated report as `machine`, which has always been just as
    self-asserted, and the dashboard uses it only to answer "is this the
    computer I already know?" for an editor it has ALREADY authenticated.
  * NOT derived from hardware. A MAC/serial/volume-id fingerprint would
    change under a NIC swap or a reimage, cannot be reset when it collides,
    and is the kind of identifier that turns into a licensing mechanism
    nobody asked for. A UUID4 in a file the editor owns is enough.
  * NOT the Syncthing device ID, which regenerates: a reinstall of Syncthing
    is exactly the event that made a machine unrecognisable on 2026-07-27
    (stuck lane C, a day to diagnose). The companion reports THAT too, but as
    an attribute of this id rather than as the identity itself.

Losing the file is not a failure that needs handling beyond re-minting: the
machine arrives under its hostname, which is what the plan is keyed on
anyway, and the dashboard's only loss is the rename affordance.

Never-raise ethos, as in identity.py/eula.py: a machine that cannot write
this file still reports, still syncs, and simply has no id.
"""

from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path
from typing import Any, Optional

from . import config as config_mod

log = logging.getLogger("ccsync.machine")

MACHINE_FILENAME = "machine.json"

# Schema version 1:
#   {"machine_id": "<uuid4 hex>", "created_at": "<iso>"}
# Unknown keys are ignored on read, so either half may add one.
_SCHEMA_VERSION = 1


def machine_path(state_dir: Optional[Path] = None) -> Path:
    """~/.ccsync/machine.json — beside identity.json, NOT under state/.

    Same reasoning as the upgrade floor: this outlives any single run and any
    single build, and `state/` is the directory a support session is most
    likely to be told to delete."""
    base = Path(state_dir) if state_dir else Path(config_mod.CONFIG_PATH).parent
    return base / MACHINE_FILENAME


def read(path: Optional[Path] = None) -> Optional[dict[str, Any]]:
    target = path or machine_path()
    try:
        data = json.loads(target.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        return None
    except Exception:
        log.warning("could not read %s -- treating this machine as unidentified", target)
        return None
    return data if isinstance(data, dict) else None


def machine_id(path: Optional[Path] = None, create: bool = True) -> str:
    """This machine's id, minting one on first call. "" when it cannot be
    read or written -- never an exception, and never a value that was not
    persisted: an id that changes every run is worse than none, because the
    dashboard would read each one as another new computer."""
    target = path or machine_path()
    record = read(target)
    existing = str((record or {}).get("machine_id") or "").strip()
    if existing:
        return existing
    if not create:
        return ""
    minted = uuid.uuid4().hex
    payload = {
        "version": _SCHEMA_VERSION,
        "machine_id": minted,
        "created_at": _now_iso(),
    }
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(target.name + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        tmp.replace(target)
    except Exception:
        log.warning("could not write %s -- this machine reports no id", target)
        return ""
    log.info("minted this machine's id (%s)", minted)
    return minted


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()
