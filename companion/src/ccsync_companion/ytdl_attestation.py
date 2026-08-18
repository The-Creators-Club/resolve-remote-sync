"""The rights/ToS attestation, recorded PER MACHINE.

COMMERCIAL_READINESS.md item 2 (2026-08-17). The dashboard records that an
editor accepted the notice (ytdl/web's `attestations` table, gating the browser
and the claim); this file records that it was accepted on THIS COMPUTER, which
is a different statement and is the one the local executor needs. An editor may
be entitled to download reference material at work and not on the laptop they
lent their flatmate; the machine that fetches the video, from its own IP, onto
its own disk, is a party to what happens.

The text is the SAME text the web UI shows -- see
ytdl/web/ytdlweb/attestation.py, which is the source, and
docs/legal/YOUTUBE_FEATURE_NOTICE.md for the operator-facing version. It is
duplicated here rather than fetched because the tray must be able to show it
with no dashboard in reach, and because a legal notice that changes underneath
the person reading it is worse than one that is a release behind. TEXT_VERSION
is pinned equal to the server's by companion/tests (and the executor sends its
version on to nothing -- the server checks its own record, this checks its own).

DRAFT FOR COUNSEL: the wording is engineering's, not a lawyer's.

State lives at ~/.ccsync/state/ytdl-attestation.json:

    {"version": "2026-08-17.1", "accepted_by": "editor1",
     "accepted_at": "2026-08-17T09:12:00+00:00"}

Never raises. An unreadable, missing, mis-versioned or wrong-editor file all
mean NOT ACCEPTED, which refuses the download -- the safe direction, and the
only one that keeps the record honest.
"""

from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from . import config as config_mod

log = logging.getLogger("ccsync.ytdl")

STATE_FILENAME = "ytdl-attestation.json"

# Pinned equal to ytdlweb.attestation.TEXT_VERSION. Bump BOTH together, or the
# two halves of the gate disagree about what the editor agreed to.
TEXT_VERSION = "2026-08-17.1"

TITLE = "Accept YouTube Terms"

# Kept in step with ytdlweb.attestation.NOTICE_TEXT. Trimmed of the numbering's
# hanging indents so it renders in a plain Tk message box.
NOTICE_TEXT = """\
This tool downloads video from YouTube at your request. Before you use it:

1. YOU CONFIRM YOU HAVE THE RIGHT TO USE THIS MATERIAL. You are the person \
choosing each clip, and you are stating that your intended use of it is \
permitted -- because you own it, because you have a licence or written \
permission, because it is public domain or openly licensed, or because your \
use is covered by an exception in your jurisdiction (for example fair dealing \
or fair use). If you are not sure, ask before you download.

2. YOU ARE RESPONSIBLE FOR COMPLYING WITH YOUTUBE'S TERMS OF SERVICE and with \
copyright law. Whether a particular download is permitted is between you (and \
your organisation) and YouTube; it is not something this software decides.

3. CC SYNC GRANTS YOU NO RIGHTS IN ANY DOWNLOADED MATERIAL. It is a tool. It \
does not license, clear, or vouch for anything it fetches.

4. WHAT IS RECORDED. Your username, this machine's name, the clip and the time \
are written to your organisation's own records. Downloads are attributed to you.

Downloads are paced deliberately and are not guaranteed to succeed: YouTube \
rate-limits, blocks and changes its service without notice, and this feature \
may stop working at any time.

Accepting records that you have read this on THIS computer, as this user.
If you cannot make these statements about the material you are about to fetch, \
do not download it.
"""

_lock = threading.Lock()


def state_path() -> Path:
    """~/.ccsync/state/ytdl-attestation.json.

    config_mod.CONFIG_DIR rather than an expanduser("~") of our own: the test
    suite repoints it at a temp tree and nothing here may escape it
    (tests/conftest.py), which is site.py's rule for the same reason.
    """
    return config_mod.CONFIG_DIR / "state" / STATE_FILENAME


def load(path: Optional[Path] = None) -> Optional[dict[str, Any]]:
    """The stored record, or None. Tolerant: any failure reads as absent."""
    target = Path(path) if path is not None else state_path()
    try:
        # utf-8-sig for the reason identity.load_identity uses it: Windows
        # tools write a BOM and a plain utf-8 read leaves "﻿{".
        data = json.loads(target.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def accepted(editor: Optional[str], path: Optional[Path] = None) -> bool:
    """Has `editor` accepted the CURRENT wording on this machine?

    Three things must line up and all three matter: the version (a re-worded
    notice re-prompts), the editor (a shared machine does not carry one
    person's acceptance over to the next), and the record existing at all.
    A blank editor is never accepted -- there is nobody to have accepted.
    """
    name = str(editor or "").strip()
    if not name:
        return False
    record = load(path) or {}
    return (str(record.get("version") or "") == TEXT_VERSION
            and str(record.get("accepted_by") or "").strip() == name)


def accept(editor: Optional[str], path: Optional[Path] = None) -> tuple[bool, str]:
    """Record acceptance. -> (ok, message the tray shows). Never raises."""
    name = str(editor or "").strip()
    if not name:
        return False, ("sign in first -- the record has to say who accepted "
                       "these terms")
    target = Path(path) if path is not None else state_path()
    payload = {
        "version": TEXT_VERSION,
        "accepted_by": name,
        "accepted_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    try:
        with _lock:
            target.parent.mkdir(parents=True, exist_ok=True)
            # tmp-then-replace, save_identity's shape: no reader ever sees
            # half a record, and a half record would read as "not accepted".
            tmp = target.with_name(target.name + ".tmp")
            tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            tmp.replace(target)
    except OSError as exc:
        log.warning("ytdl: could not record the attestation at %s (%s)", target, exc)
        return False, f"couldn't save that ({exc})"
    log.info("ytdl: %s accepted the download terms (%s) on this machine",
             name, TEXT_VERSION)
    return True, ("Recorded. YouTube downloads can now run on this machine, "
                  "for you.")
