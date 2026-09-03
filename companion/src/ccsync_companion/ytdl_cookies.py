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

import calendar
import json
import logging
import os
import time
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
               "site. Ask your administrator (site.toml [features] "
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
        return False, ("that is not a cookies.txt in Netscape format. Export it "
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
                       "(no login cookies found). Sign in to YouTube in the "
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
    try:
        with open(str(src_path), "r", encoding="utf-8", errors="replace") as fh:
            text = fh.read()
    except OSError as exc:
        return False, f"couldn't read that file ({exc})"
    return install_text(text, dest)


def install_text(text: Any, dest: Optional[Path] = None) -> tuple[bool, str]:
    """Validate cookies.txt CONTENT and write it to the default path 0600.

    The half of install() that does not involve a source file, split out on
    2026-08-17 so the browser sign-in (ytdl_browser_login.py) -- which has
    the cookies in memory, straight from the browser -- lands on exactly the
    same validate + harden + tmp-then-replace path as a picked file. Same
    (ok, message) contract, same site gate, never raises."""
    if not enabled():
        return False, OFF_MESSAGE
    target = dest if dest is not None else default_cookies_path()
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
    mark_ok("fresh sign-in")
    return True, "YouTube sign-in saved: your downloads can now reach age-restricted clips"


# ---------------------------------------------------------------- health
# Cookies stop working in two ways and neither is announced: Google ROTATES
# the session (the file is intact, the values are dead -- yt-dlp says "cookies
# are no longer valid ... likely been rotated"), or the session cookies simply
# EXPIRE. Either way the next age-gated clip quietly falls back to the server
# and the editor never learns their sign-in is gone. So (2026-08-17, at the
# user's request) the executor reports what yt-dlp told it, and the tray warns
# from that record until the editor signs in again.
STATUS_FILENAME = "ytdl-cookies-status.json"
STATUS_OK = "ok"
STATUS_STALE = "stale"          # yt-dlp refused the session on a real download
STATUS_EXPIRED = "expired"      # the login cookies in the file are past their expiry
STATUS_NONE = "none"            # no cookies file at all

# CYT-5 (usability sweep 2026-09-04): a `stale` record with nothing since is
# not evidence of anything after a while. Since WP3 made the jar a FALLBACK,
# cookied downloads are rare, so the last word on the session can be months
# old -- and the CR-80 variant is worse, because its remedy is to do nothing,
# so the warning could never retire. Past this age the record still stands
# (it is the only word we have) but it is reported as ageing, and the tray
# says so calmly instead of asking for a sign-in nothing has tested.
STALE_MAX_AGE_DAYS = 7

# yt-dlp stderr fragments that mean "the session you gave me does not work",
# as opposed to a network blip or a private video. Lower-cased substring
# matches; each is a phrase yt-dlp has used verbatim. Matched ONLY when a
# cookies file was actually passed -- without one, "not a bot" is the plain
# anonymous bot-check and says nothing about the editor's sign-in.
STALE_SIGNATURES = (
    "cookies are no longer valid",           # "The provided YouTube account cookies are no longer valid. They have likely been rotated..."
    "sign in to confirm you're not a bot",   # bot check hit even though we sent a session
    "sign in to confirm your age",           # age gate not lifted -> the session is not a signed-in one any more
    "this video may be inappropriate for some users",
    "please sign in to view this video",
    "login required",
    # CR-80 (2026-08-26): YouTube refusing a signed-in session it has FLAGGED.
    # Not an expiry and not a rotation -- the cookies still authenticate (the
    # subscriptions feed listed fine with them all through the incident), so
    # nothing else in this module would ever have noticed. What YouTube does
    # is downgrade the `tv` client to UNPLAYABLE and SABR-force every https
    # format away, and the message it leaves names a page reload that no
    # downloader can perform. It is a PLAYBACK flag on the account, which is
    # why the remedy is a different export rather than a fresh sign-in to the
    # same one, and why the executor's answer is to fall back to anonymous
    # (plan WP3) rather than to give up.
    "the page needs to be reloaded",
)

# The one signature above whose remedy is not "sign in again": the tray line
# has to say something different for it (see stale_reason).
ACCOUNT_FLAG_SIGNATURE = "the page needs to be reloaded"


def stale_reason(sig: Any) -> str:
    """The recorded `reason` for a matched stale signature, in the editor's
    words. Pure; never raises.

    The reason is read by a person (tray._youtube_warning_line), so a flagged
    account must not arrive as "yt-dlp: the page needs to be reloaded" -- the
    string that cost CR-80 a day of guessing. It keeps the signature inside it
    so the tray can still tell the two cases apart by text.
    """
    text = str(sig or "")
    if ACCOUNT_FLAG_SIGNATURE in text.lower():
        return ("YouTube is refusing your signed-in session (the page needs to "
                "be reloaded). Downloads are continuing without it.")
    return f"yt-dlp: {text}"


def status_path() -> Path:
    return Path.home() / ".ccsync" / "state" / STATUS_FILENAME


def _write_status(status: str, reason: str, path: Optional[Path] = None) -> None:
    target = path or status_path()
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(target.suffix + ".new")
        tmp.write_text(json.dumps({"status": status, "reason": reason,
                                   "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}),
                       encoding="utf-8")
        os.replace(tmp, target)
    except OSError:
        log.debug("ytdl cookies: could not write status", exc_info=True)


def mark_stale(reason: str, path: Optional[Path] = None) -> None:
    """A real download with the editor's cookies was refused for a reason
    that means the session is dead. Idempotent; never raises."""
    log.warning("ytdl cookies: the signed-in session no longer works (%s)", reason)
    _write_status(STATUS_STALE, str(reason or "")[:300], path)


def mark_ok(reason: str = "", path: Optional[Path] = None) -> None:
    """A cookied download succeeded, or a fresh sign-in was installed."""
    _write_status(STATUS_OK, reason, path)


def recorded_status(path: Optional[Path] = None) -> str:
    """The STATUS FILE's own word, with no cookie-file reads and no inference:
    "ok" / "stale" / "" when there is no readable record.

    CYT-5 (2026-09-04): the clear path used to be gated on a PER-JOB memo
    (`DownloadJob._cookie_health_stale`, initialised False in every new job),
    so a stale mark could only ever be cleared inside the very job that wrote
    it. Every later successful cookied download took the early-return path
    without calling mark_ok, and the tray asked for a fresh sign-in forever.
    The file is the authority; this is how a caller asks it. Never raises."""
    target = path or status_path()
    try:
        if not target.is_file():
            return ""
        rec = json.loads(target.read_text(encoding="utf-8")) or {}
    except (OSError, ValueError):
        return ""
    except Exception:
        log.debug("ytdl cookies: status unreadable", exc_info=True)
        return ""
    return str(rec.get("status") or "")


def _record_age_days(at: str, now: Optional[float] = None) -> Optional[float]:
    """Days since a record's `at` stamp, or None when it cannot be read.

    None is "we cannot tell", and the caller treats that as NOT aged: a
    warning that retires itself because a timestamp was unparseable is the
    opposite of the point."""
    text = str(at or "").strip()
    if not text:
        return None
    try:
        stamp = time.strptime(text, "%Y-%m-%dT%H:%M:%SZ")
    except (ValueError, TypeError):
        return None
    seconds = (now if now is not None else time.time()) - calendar.timegm(stamp)
    return seconds / 86400.0


def classify_failure(stderr: Any, cookies_used: bool) -> Optional[str]:
    """The stale-signature that matched, or None. `cookies_used` False -> None
    always (see STALE_SIGNATURES)."""
    if not cookies_used:
        return None
    low = str(stderr or "").lower()
    for sig in STALE_SIGNATURES:
        if sig in low:
            return sig
    return None


def _session_expiry(text: str) -> Optional[int]:
    """The LATEST expiry among the login cookies in a Netscape file, or None
    when there are none / all are session cookies (expiry 0)."""
    latest = None
    for line in str(text or "").splitlines():
        if not line or "\t" not in line:
            continue
        fields = line.split("\t")
        if len(fields) < 7:
            continue
        domain, expiry, name = fields[0], fields[4], fields[5]
        if "youtube.com" not in domain or name not in _SESSION_COOKIE_NAMES:
            continue
        try:
            exp = int(float(expiry))
        except ValueError:
            continue
        if exp > 0 and (latest is None or exp > latest):
            latest = exp
    return latest


def health(cfg: Optional[dict[str, Any]] = None, path: Optional[Path] = None,
           now: Optional[float] = None) -> dict[str, Any]:
    """{status, reason, at} for the tray. Never raises; cheap (two small
    reads). Order of precedence: no file -> none; a recorded STALE (yt-dlp's
    verdict beats anything we can infer); expired login cookies -> expired;
    else ok."""
    out = {"status": STATUS_NONE, "reason": "", "at": ""}
    try:
        cookies_file = resolve(cfg) if enabled() else None
        if not cookies_file:
            return out
        target = path or status_path()
        rec: dict[str, Any] = {}
        if target.is_file():
            try:
                rec = json.loads(target.read_text(encoding="utf-8")) or {}
            except (OSError, ValueError):
                rec = {}
        if rec.get("status") == STATUS_STALE:
            # CYT-5: `aged` is the difference between "your sign-in stopped
            # working" and "nothing has used your sign-in for a week", which
            # are the same record and very different sentences.
            age = _record_age_days(str(rec.get("at") or ""), now)
            return {"status": STATUS_STALE, "reason": str(rec.get("reason") or ""),
                    "at": str(rec.get("at") or ""),
                    "aged": bool(age is not None and age > STALE_MAX_AGE_DAYS)}
        try:
            text = Path(cookies_file).read_text(encoding="utf-8", errors="replace")
        except OSError:
            return out
        exp = _session_expiry(text)
        if exp is not None and exp < (now if now is not None else time.time()):
            return {"status": STATUS_EXPIRED, "reason": "the login cookies in the file have expired",
                    "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(exp))}
        return {"status": STATUS_OK, "reason": str(rec.get("reason") or ""),
                "at": str(rec.get("at") or "")}
    except Exception:  # noqa: BLE001 -- a tray line must never take the tray down
        log.debug("ytdl cookies: health unreadable", exc_info=True)
        return out
