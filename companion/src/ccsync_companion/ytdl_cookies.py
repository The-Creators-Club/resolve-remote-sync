"""Where the local YouTube downloader's signed-in cookies live, and how the
tray's "Sign in to YouTube" installs them.

WHY (2026-08-16). A signed-in cookies.txt is what lets an editor's own machine
pass YouTube's bot check and download age-restricted clips, instead of handing
those jobs back to the server. There are two ways to point the downloader at
one, and this module is the seam both go through:

  1. `ytdl_cookies_file` in config.toml -- an editor who manages their own
     file (a scripted export, a shared path) sets it and it always wins.
  2. the DEFAULT path, `~/.ccsync/youtube-cookies.txt`, which the tray's
     "Sign in to YouTube (for downloads)…" writes by copying a cookies.txt the
     editor exported from their browser. This exists BECAUSE the companion has
     no config writer -- config.toml is hand-edited and read-only here -- so a
     GUI that "saves" a setting has to save it as a file at a known path, not
     as a line in the TOML.

The config key beats the default path so an explicit choice is never
overridden by a leftover file, and either being absent is the anonymous case
(public clips only; age-gated ones fall back to the server).

A `cookies.txt` is a live Google session and the same SID/SAPISID values Google
uses across *.google.com -- so `install()` refuses a file that is not what it
claims (a Netscape header, real youtube.com session cookies) rather than copy
arbitrary bytes into place, and the file is written 0600. It does NOT try to
judge whether the session is age-verified or fresh: yt-dlp is the authority on
whether cookies actually work, and a validator that guessed would reject good
files and pass stale ones. It checks SHAPE, not liveness.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Optional

from . import secretfile

log = logging.getLogger("ccsync.ytdl")

# ~/.ccsync/youtube-cookies.txt. Path.home()/".ccsync" is where config.toml,
# the log and the state dir already live (config.CONFIG_DIR), but importing
# that here would be a cycle in some load orders, and the directory derivation
# is one line.
COOKIES_FILENAME = "youtube-cookies.txt"

# The session cookies a signed-in youtube.com export must contain. Not the
# whole set -- __Secure-3P* alone is what the NAS's half-broken file carried
# (2026-08-16) and it does NOT authenticate. These are the ones a real logged
# in session has; requiring a couple of them rejects a logged-OUT export
# (consent/visitor cookies only) without demanding an exact list yt-dlp does
# not.
_SESSION_COOKIE_NAMES = ("SID", "SAPISID", "SSID", "HSID", "APISID", "LOGIN_INFO")
_MIN_SESSION_COOKIES = 2

# The refusal an off site gets, in the editor's words. One string so the tray
# item and the resolver never tell different stories.
OFF_MESSAGE = ("signing in to YouTube for downloads is not enabled for this "
               "site — ask your administrator (site.toml [features] "
               "youtube_unblock)")


def enabled() -> bool:
    """May this machine download as a SIGNED-IN YouTube account?

    Off unless the customer's site manifest says `youtube_unblock`
    (2026-08-17, docs/COMMERCIAL_READINESS.md item 3). Downloading with a
    person's live Google session is the component that most obviously
    engages YouTube's Terms of Service, so the vendor build does not offer
    it and a customer who is entitled to it turns it on for their own site.
    The code stays here, dormant. Fails closed and never raises; the deferred
    import avoids a cycle (site -> config -> ...).
    """
    try:
        from . import ytdlp_manager

        return ytdlp_manager.unblock_enabled()
    except Exception:                          # noqa: BLE001 - never raises
        log.debug("ytdl cookies: unblock flag unreadable; treating it as off",
                  exc_info=True)
        return False


def default_cookies_path() -> Path:
    return Path.home() / ".ccsync" / COOKIES_FILENAME


def resolve(cfg: Optional[dict[str, Any]]) -> Optional[str]:
    """The cookies file the downloader should use, or None. Never raises.

    Config key (if set and present) beats the tray-written default path (if
    present); neither is the anonymous case. Existence is checked here so the
    executor can treat the answer as "pass this to yt-dlp" with no second
    stat -- a configured-but-missing path is None, not an error, because a
    missing --cookies file aborts the whole yt-dlp run.

    None ALSO when the site has not enabled `youtube_unblock`, even if a file
    is sitting at either path from before the flag existed: the switch has to
    stop yt-dlp being handed a live Google session, not merely stop the tray
    writing one (2026-08-17)."""
    if not enabled():
        return None
    try:
        configured = str((cfg or {}).get("ytdl_cookies_file", "") or "").strip()
        if configured:
            path = os.path.expanduser(configured)
            return path if os.path.isfile(path) else None
        default = default_cookies_path()
        return str(default) if default.is_file() else None
    except Exception:
        log.debug("ytdl cookies: resolve failed", exc_info=True)
        return None


def validate(text: Any) -> tuple[bool, str]:
    """Is `text` a Netscape cookies.txt carrying a signed-in youtube session?

    (ok, message). SHAPE only -- see the module docstring. The message is
    editor-facing: it lands in the tray dialog's status line."""
    try:
        lines = str(text or "").splitlines()
    except Exception:
        return False, "that file could not be read as text"

    if not any(line.strip().lower().startswith("# netscape") or "\t" in line
               for line in lines):
        return False, ("that is not a cookies.txt in Netscape format — export it "
                       "with a \"cookies.txt\" browser extension, not Save As")

    found = set()
    for line in lines:
        if line.startswith("#") or "\t" not in line:
            continue
        fields = line.split("\t")
        if len(fields) < 7:
            continue
        domain, name = fields[0], fields[5]
        if "youtube.com" in domain and name in _SESSION_COOKIE_NAMES:
            found.add(name)

    if len(found) < _MIN_SESSION_COOKIES:
        return False, ("those cookies are not from a signed-in YouTube session "
                       "(no login cookies found) — sign in to YouTube in the "
                       "browser first, then export")
    return True, f"signed-in session found ({len(found)} login cookies)"


def install(src_path: Any, dest: Optional[Path] = None) -> tuple[bool, str]:
    """Validate the file at `src_path` and copy it to the default path 0600.

    (ok, message), never raises. `dest` overrides the destination for tests.

    Refused outright on a site that has not enabled `youtube_unblock` -- the
    tray hides the item there, so reaching this is a direct call or a stale
    menu, and neither should end with a Google session on disk."""
    if not enabled():
        return False, OFF_MESSAGE
    target = dest if dest is not None else default_cookies_path()
    try:
        with open(str(src_path), "r", encoding="utf-8", errors="replace") as fh:
            text = fh.read()
    except OSError as exc:
        return False, f"couldn't read that file ({exc})"

    ok, message = validate(text)
    if not ok:
        return False, message

    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        # Write then harden, not copy2: the source's permissions are the
        # browser-download dir's, and this file is a live Google session -- it
        # gets owner-only regardless of where it came from. A tmp-then-replace
        # so a killed write never leaves a half file the downloader would send.
        #
        # secretfile.harden, NOT os.chmod (2026-08-17,
        # COMMERCIAL_READINESS.md item 5): os.chmod(0o600) is a NO-OP on
        # Windows, which is where most of this fleet's editors are, so the
        # cookie jar sat at whatever the profile's inherited ACL was -- the
        # one file here that is a logged-in account. harden() sets an
        # owner-only ACL there and 0600 on posix, and hardens the TEMP file
        # before the rename so the secret is never briefly world-readable.
        tmp = target.with_suffix(target.suffix + ".new")
        tmp.write_text(text, encoding="utf-8")
        secretfile.harden(tmp)
        os.replace(tmp, target)
    except OSError as exc:
        return False, f"couldn't save the cookies ({exc})"
    log.info("ytdl cookies: installed a signed-in session at %s", target)
    return True, "YouTube sign-in saved — your downloads can now reach age-restricted clips"
