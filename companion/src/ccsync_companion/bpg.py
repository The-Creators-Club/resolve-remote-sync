"""Launch the Blackmagic Proxy Generator for the clips ffmpeg cannot touch.

proxy_gen encodes everything ffmpeg can decode and deliberately never queues
BRAW/R3D/CRM: ffmpeg cannot decode them at any quality, and promising a proxy
this machine cannot make is worse than reporting the gap. BPG is the answer for
those, and until now "the answer" meant remembering to open it -- which is why
the base rig sat with 6 BRAW clips unproxied while BPG had not run since 00:41
that morning (2026-08-10).

Four facts shape everything here, all established on the base rig:

  1. BPG IS RESOLVE. The Start-menu entry is a shortcut to
     `Resolve.exe -pg`, not a separate binary. So "is BPG running" cannot be
     answered by process NAME -- plain Resolve and BPG are the same image, and
     only the command line separates them.
  2. It is a WATCHER, not a job runner. It takes no file arguments; it scans
     the folders in its own INI (`watchFolderList`) and picks up whatever
     lacks a proxy. So this module cannot say WHAT to encode, only WHERE to
     look -- which is why `watch_dirs` is the directories the pending
     BRAW/R3D/CRM clips sit in, and why everything else in those directories
     gets a proxy too (see the collateral note below).
  3. An EMPTY watch list is a silent no-op, and the list empties itself.
     `watchFolderList=@Invalid()` is what Qt writes for "no folders", and BPG
     rewrites the INI from its in-memory list every time it exits -- so a
     folder the user removed, or one BPG dropped because the drive was away,
     is gone for good. On 2026-08-13 the base rig had exactly that: an
     `@Invalid()` list, 6 BRAW clips with no proxy since 2026-05-20, and this
     module dutifully starting a generator that watched NOTHING three times a
     day (14:09, 15:26, 18:13) while the gap never moved. Hence
     `ensure_watch_folders`: the launcher now seeds the list before it starts
     anything, ADDITIVELY (a user entry is never removed or rewritten -- new
     entries are appended to the existing value text verbatim) and only while
     BPG is DOWN, since a running one would overwrite the file on exit.
  4. It does NOT start itself. The window opens Idle with a Start button and
     the watch folders sitting at "Waiting" -- measured on the same rig the
     same day, which is the other half of why three launches encoded nothing.
     There is no command line, environment variable or INI key for it: the
     only way in is the button, so `press_start` drives the UI Automation
     tree (PowerShell + UIAutomationClient, the same shell-out the CIM probe
     already uses). The control is a checkbox whose NAME is its action --
     "Start" when idle, "Stop" when running -- so reading it is how we know
     which state BPG is in, and pressing it is only ever done when it says
     "Start". InvokePattern.Invoke() works; TogglePattern.Toggle() flips the
     accessibility state without running the click handler (tested, 2026-08-13)
     -- do not "simplify" it back.

COLLATERAL, accepted deliberately: BPG proxies EVERY unproxied clip in a
watched folder, and it does not recognise this companion's `Proxy/<stem>.mp4`
as a proxy -- only its own `Proxy/<stem>.mov`. Handing it one editor's folder
(6 BRAW gaps) therefore queued 179 items, 173 of which already had an ffmpeg
proxy, for ~3.8 GB of duplicates. That is the price of a watcher that takes no
file list, and it is paid per FOLDER, so the watch dirs stay as narrow as the
scan can make them (the clip's own directory, never the project root).
KNOWN_BUGS R14 records the alternative -- make proxy_gen write `.mov` so BPG
recognises its output -- and where that decision stands.

Sequencing, per the design this was asked for: BPG starts only once the ffmpeg
queue is EMPTY, so the two never encode at the same time. Running it alongside
an open Resolve is explicitly allowed (they are the same engine and it
self-throttles), unlike the ffmpeg path's optional Resolve gate.

Nothing here ever kills it. The ffmpeg child is safe to kill because proxy_gen
writes `<stem>.mp4.partial` and only ever os.replaces onto a name that does not
exist -- an interrupted encode leaves nothing behind. BPG's write behaviour is
its own and unobserved, and lane B would happily fan out a truncated proxy, so
a started BPG is left to finish. That is the conservative half of the contract:
we choose when it starts, never when it stops -- and it survives `press_start`
too, which presses the button only when it reads "Start" and never when it
reads "Stop".
"""
from __future__ import annotations

import logging
import ntpath
import os
import platform
import re
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable, Iterable, Optional, Sequence, Union

from . import canon, resolve_bridge

log = logging.getLogger("ccsync.bpg")

# `-pg` is the whole difference between the proxy generator and the editor.
BPG_FLAG = "-pg"

# Where Resolve installs on Windows. The Start-menu .lnk points here; reading
# the shortcut would need COM for no gain, since the install path is fixed.
WINDOWS_RESOLVE_EXE = r"C:\Program Files\Blackmagic Design\DaVinci Resolve\Resolve.exe"

# Don't retry a launch more often than this. If BPG exits immediately -- no
# licence, a dialog, an install that has moved -- a tick-rate relaunch would
# spawn Resolve every 15 seconds for as long as the gap exists.
RELAUNCH_COOLDOWN_SECONDS = 1800

# The CIM probe is a PowerShell spawn, and the gate asks on every 15 s tick for
# as long as a BRAW gap exists: the launcher's cheap short-circuit only covers
# a BPG *we* started, so an editor who opened it from the Start menu paid a
# PowerShell per tick (MED-9, 2026-08-11). TTL-cached on
# resolve_bridge._PROBE_TTL_SECONDS' precedent. Longer than that one because
# the answer only decides whether to start a SECOND generator, and the
# 30-minute relaunch cooldown is the real backstop against a launch storm.
_PROBE_TTL_SECONDS = 60.0
_PROBE_LOCK = threading.Lock()
_probe_cache: Optional[tuple[float, Optional[list[str]]]] = None

# BPG's settings file, relative to %APPDATA%. Qt (QSettings, IniFormat) owns
# the format; the keys are BPG's own.
SETTINGS_RELPATH = (
    "Blackmagic Design", "Blackmagic Proxy Generator",
    "Preferences", "ProxyGeneratorSettings.ini",
)
WATCH_KEY = "watchFolderList"

# What Qt writes for an invalid/empty QVariant, and what the base rig's list
# had decayed to (fact 3). Read as "no watch folders", never as a path.
INVALID_MARKER = "@Invalid()"

# The user's list before this module first touched it, kept ONCE and never
# overwritten: the point is that the original is always recoverable, not that
# the last write is.
BACKUP_SUFFIX = ".ccsync-backup"

# Ceilings on what we will add to somebody's settings file. A base rig with a
# hundred BRAW-bearing folders must not turn the watch list into a hundred
# recursive scans -- BPG rescans every entry on every change.
MAX_ADDED_PER_LAUNCH = 8
MAX_WATCH_FOLDERS = 32

# How long the start-press waits for the window. BPG is Resolve: it loads the
# codec libraries, probes the GPUs and mounts the disk database before the
# dialog appears (4.5 s on the base rig with a warm cache, and this machine is
# the fast one).
START_WAIT_SECONDS = 180

# A running BPG that is sitting Idle gets poked at most this often. The press
# is a PowerShell spawn on a 15 s tick, which is exactly the cost MED-9 was
# about; five minutes is short enough that an editor who pressed Stop by
# accident is not stuck, and long enough that it is not a per-tick cost.
START_POKE_COOLDOWN_SECONDS = 300

# The UI Automation press, in the one language that already ships on every
# Windows box in the fleet. Kept as a script rather than a ctypes IUIAutomation
# port on purpose: the CIM probe set the precedent, and comtypes/pywinauto
# under PyInstaller is a packaging problem for a button.
#
# Prints ONE token: pressed / already-running / no-window / no-button /
# unknown-<name>. The wait loop lives INSIDE the script so a cold start costs
# one PowerShell, not one per retry.
_START_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName UIAutomationClient, UIAutomationTypes
$deadline = (Get-Date).AddSeconds(__WAIT__)
$auto = [System.Windows.Automation.AutomationElement]
$titleCond = New-Object System.Windows.Automation.PropertyCondition($auto::NameProperty, 'Blackmagic Proxy Generator')
$boxCond = New-Object System.Windows.Automation.PropertyCondition($auto::ControlTypeProperty, [System.Windows.Automation.ControlType]::CheckBox)
do {
  $win = $auto::RootElement.FindFirst([System.Windows.Automation.TreeScope]::Children, $titleCond)
  if ($win) {
    $box = $win.FindFirst([System.Windows.Automation.TreeScope]::Descendants, $boxCond)
    if ($box) {
      $name = $box.Current.Name
      if ($name -eq 'Stop') { 'already-running'; exit 0 }
      if ($name -eq 'Start') {
        $box.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern).Invoke()
        Start-Sleep -Milliseconds 1500
        $after = $win.FindFirst([System.Windows.Automation.TreeScope]::Descendants, $boxCond)
        if ($after -and $after.Current.Name -eq 'Stop') { 'pressed'; exit 0 }
        'pressed-no-change'; exit 0
      }
      "unknown-$name"; exit 0
    }
  }
  Start-Sleep -Seconds 3
} while ((Get-Date) -lt $deadline)
if ($win) { 'no-button' } else { 'no-window' }
"""


def _reset_probe_cache() -> None:
    """Forget the cached process list. For tests, and for a launch we just made."""
    global _probe_cache
    with _PROBE_LOCK:
        _probe_cache = None


def find_bpg_command(configured: str = "") -> Optional[list[str]]:
    """The argv that starts the proxy generator, or None.

    Windows only, on purpose: BRAW, BPG and the base rig are all Windows here,
    and inventing a macOS path that has never been run would be a guess
    presented as support.
    """
    if configured:
        exe = Path(configured).expanduser()
        return [str(exe), BPG_FLAG] if exe.is_file() else None
    if platform.system() != "Windows":
        return None
    exe = Path(WINDOWS_RESOLVE_EXE)
    return [str(exe), BPG_FLAG] if exe.is_file() else None


def _cim_command_lines() -> Optional[list[str]]:
    """Command lines of every running Resolve.exe, or None if we cannot tell.

    tasklist cannot do this -- it reports image names, and BPG's image name is
    Resolve.exe like the editor's. None means "unknown", which callers treat
    as "not running" rather than blocking a launch: the cost of a wrong launch
    is Resolve focusing a window it already has open, and the cost of a wrong
    "already running" is the BRAW gap never closing.
    """
    global _probe_cache
    if platform.system() != "Windows":
        return None
    with _PROBE_LOCK:
        cached = _probe_cache
        if cached is not None and (time.monotonic() - cached[0]) < _PROBE_TTL_SECONDS:
            return cached[1]
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-CimInstance Win32_Process -Filter \"Name='Resolve.exe'\" "
             "| ForEach-Object { $_.CommandLine }"],
            capture_output=True, text=True, timeout=30,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            # The same rule as the launch spawn below (COMP-MEDIA-3): no child
            # of a frozen companion inherits the _MEI Python pins.
            env=resolve_bridge.sanitized_child_env(),
        )
    except Exception:
        log.debug("bpg: could not read Resolve command lines", exc_info=True)
        lines = None
    else:
        lines = (
            None if out.returncode != 0
            else [ln.strip() for ln in (out.stdout or "").splitlines() if ln.strip()]
        )
    # A failed read is cached too: it means the same as an empty one to every
    # caller, and re-spawning PowerShell every 15 s to be told nothing again is
    # the cost this cache exists to remove.
    with _PROBE_LOCK:
        _probe_cache = (time.monotonic(), lines)
    return lines


def is_bpg_running(command_lines_fn: Callable[[], Optional[list[str]]] = _cim_command_lines) -> bool:
    """Is a Resolve running in proxy-generator mode?

    Matched on the `-pg` argument, since the image name is shared with the
    editor. An unreadable process list is reported as NOT running -- see
    _cim_command_lines.
    """
    lines = command_lines_fn()
    if not lines:
        return False
    return any(BPG_FLAG in line.split() for line in lines)


# -- the watch list (fact 3) --------------------------------------------------

def settings_path(configured: str = "") -> str:
    """Where BPG keeps its watch folders, or "" if we cannot know.

    %APPDATA% rather than a hardcoded C:\\Users\\...: the fleet has roaming
    profiles on at least one machine, and Qt asks Windows the same question.
    """
    if configured:
        return str(Path(configured).expanduser())
    appdata = os.environ.get("APPDATA") or ""
    if not appdata:
        return ""
    return os.path.join(appdata, *SETTINGS_RELPATH)


def parse_watch_folders(value: Any) -> list[str]:
    """The folders in a Qt QStringList value: comma-separated, backslash-escaped.

    Used ONLY to decide whether a folder is already covered -- the entries it
    returns are never written back. Qt's escaping has corners this does not
    model (`\\xNN` for control characters, chiefly), and a path this mis-reads
    must cost at most one redundant entry, never a rewritten one.
    """
    text = str(value or "").strip()
    if not text or text == INVALID_MARKER:
        return []
    out: list[str] = []
    buf: list[str] = []
    quoted = False
    index = 0
    while index < len(text):
        char = text[index]
        if char == "\\" and index + 1 < len(text):
            if text[index + 1] == "x":
                # Qt's \xHHHH: greedy over hex digits, one UTF-16 code unit.
                end = index + 2
                while end < len(text) and text[end] in "0123456789abcdefABCDEF":
                    end += 1
                if end > index + 2:
                    buf.append(chr(int(text[index + 2:end], 16) & 0xFFFF))
                    index = end
                    continue
            buf.append(text[index + 1])
            index += 2
            continue
        if char == '"':
            quoted = not quoted
            index += 1
            continue
        if char == "," and not quoted:
            out.append("".join(buf).strip())
            buf = []
            index += 1
            continue
        buf.append(char)
        index += 1
    out.append("".join(buf).strip())
    # Qt's \x escapes are UTF-16 code units: rejoin surrogate pairs.
    return [entry.encode("utf-16", "surrogatepass").decode("utf-16", "replace")
            for entry in out if entry]


def _qt_escape_text(path: str) -> str:
    r"""Backslash-escape one string the way Qt 5's QSettings INI writer does.

    BPG reads its .ini as Latin-1 (Qt 5 with no iniCodec), so a non-Latin-1
    character can only reach it as Qt's own `\xHHHH` escape: the UTF-16 code
    unit in hex, which Qt's reader turns back into the character. Writing the
    UTF-8 bytes instead (what this did until 2026-08-21, CR-69) gave BPG a
    mojibake folder -- the real folder name arrived as `ç¬¬ä¸‰å±†...` -- that
    it listed, never found on disk, and rewrote as `\xe7\xac\xac...` on exit,
    so every later launch saw an uncovered folder and appended another copy.

    Qt's reader is greedy after `\x`: it keeps consuming hex digits, so a
    character that FOLLOWS an escape and is itself a hex digit (`0-9a-fA-F`)
    must be escaped too or it is swallowed into the code point -- Qt's writer
    has the same `escapeNextIfDigit` rule. Astral characters are two code
    units, as they are in QString.
    """
    out: list[str] = []
    escape_next_digit = False
    for char in path:
        code = ord(char)
        if code > 0xFFFF:
            code -= 0x10000
            units = (0xD800 | (code >> 10), 0xDC00 | (code & 0x3FF))
        else:
            units = (code,)
        for unit in units:
            if unit == 0x5C:
                out.append("\\\\")
                escape_next_digit = False
            elif unit == 0x22:
                out.append('\\"')
                escape_next_digit = False
            elif unit < 0x20 or unit > 0x7E or (
                    escape_next_digit and chr(unit) in "0123456789abcdefABCDEF"):
                out.append("\\x%x" % unit)
                escape_next_digit = True
            else:
                out.append(chr(unit))
                escape_next_digit = False
    return "".join(out)


def _mojibake_of(entry: str, wanted: Sequence[str]) -> bool:
    r"""Is `entry` the Latin-1 misreading of one of the folders we want?

    The damage CR-69 left behind in the field: our UTF-8 bytes, read by BPG as
    Latin-1 and written back by it as \xHH escapes, parse to a string whose
    Latin-1 encoding is the UTF-8 of the real folder. Only OUR past entries
    can have that shape, so dropping them rewrites nothing of the editor's.
    """
    try:
        decoded = entry.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return False
    if decoded == entry:
        return False
    target = _norm(decoded)
    return any(target == _norm(item) for item in wanted)


def _escape_watch_folder(path: str) -> str:
    """One folder, in the spelling Qt reads back as the same string.

    Verified against a live BPG on 2026-08-13: `P:\\\\Projects\\\\...` with
    unescaped interior spaces is what it accepts (the window listed the folder
    and costed the encode). Quoting is only for the characters that would
    otherwise end the element; non-ASCII goes through _qt_escape_text.
    """
    escaped = _qt_escape_text(path)
    if (any(char in escaped for char in ',;="')
            or escaped != escaped.strip()):
        return '"' + escaped + '"'
    return escaped


def _norm(path: Any) -> str:
    """Case/separator-folded, in the string's OWN spelling.

    Watch-folder entries are always canonical `P:\\Projects\\...` strings --
    BPG itself only ever runs on Windows (find_bpg_command above) -- so this
    must fold backslashes and case even when the companion process is not on
    Windows (macOS CI, 2026-08-17: os.path there is posixpath, which treats
    `\\` as an ordinary filename character and does not lowercase, so two
    spellings of the same watch folder stopped comparing equal). canon.norm
    is the package's one place that already knows this rule.
    """
    return canon.norm(str(path or "").strip())


def _is_covered(wanted: str, entries: Iterable[str]) -> bool:
    """Would BPG already find this folder? Watch folders are RECURSIVE, so an
    ancestor counts -- an editor watching `P:\\Projects` needs nothing added."""
    target = _norm(wanted)
    if not target:
        return True
    sep = ntpath.sep  # these are always Windows-spelled, not the host's os.sep
    for entry in entries:
        existing = _norm(entry)
        if not existing:
            continue
        if target == existing or target.startswith(existing.rstrip(sep) + sep):
            return True
    return False


_WATCH_LINE_RE = re.compile(
    r"^(?P<key>[ \t]*" + WATCH_KEY + r"[ \t]*=[ \t]*)(?P<value>.*?)[ \t]*$",
    re.MULTILINE,
)
_GENERAL_RE = re.compile(r"^\[General\][ \t]*$", re.MULTILINE)


def ensure_watch_folders(wanted: Sequence[str], *, path: str = "",
                         create_dir: bool = False) -> dict[str, Any]:
    """Add the folders BPG needs to watch, without touching the ones it has.

    ADDITIVE and text-preserving: the existing value is carried over verbatim
    and our entries are appended to it, so a settings file we parse imperfectly
    still comes out with the user's list intact. Only ever called while BPG is
    down -- a running one rewrites this file from memory when it exits.

    `create_dir` says the caller has already established that this machine HAS
    a proxy generator (find_bpg_command found Resolve.exe), so the Preferences
    directory may be created. It defaults False so a bare call still refuses to
    scatter a config on a machine with no BPG -- but the launcher passes True,
    because `%APPDATA%\\Blackmagic Design\\Blackmagic Proxy Generator\\
    Preferences` is created by BPG's first RUN, not by the Resolve installer
    (measured on the base rig: that tree and BPG's own rollinglog.txt share a
    creation second, months after Resolve's own appdata dir). Refusing without
    it meant the precondition for launching BPG was that BPG had already been
    launched -- i.e. the whole R14 feature was inert on exactly the machines it
    exists for (COMP-MEDIA-6, 2026-08-14).

    Returns {"ok", "added", "reason"}. Never raises: a settings file we cannot
    read is a reason not to launch, not a crash.
    """
    result: dict[str, Any] = {"ok": False, "added": [], "reason": ""}
    seen: set[str] = set()
    dirs: list[str] = []
    for entry in wanted or ():
        text = str(entry or "").strip()
        if not text or _norm(text) in seen:
            continue
        seen.add(_norm(text))
        dirs.append(text)
    if not dirs:
        # Nothing to add: this is a no-op regardless of whether a settings
        # path exists at all, so it must not depend on target below -- a
        # caller with an empty want list (maybe_launch's default watch_dirs)
        # on a machine that cannot resolve %APPDATA% (any non-Windows host,
        # e.g. macOS CI, 2026-08-17) got "watch folders could not be set" for
        # a launch that had nothing to watch anyway.
        result["ok"] = True
        return result
    target = path or settings_path()
    if not target:
        result["reason"] = "no %APPDATA%"
        return result
    try:
        try:
            with open(target, "r", encoding="utf-8", newline="") as handle:
                content = handle.read()
        except FileNotFoundError:
            # BPG that has never been opened has no settings file, and on a
            # machine where it has never RUN there is no directory either.
            # Writing one is fine where there is a proxy generator to read it
            # (create_dir); anywhere else a stray config is worse than a
            # refusal.
            directory = os.path.dirname(target)
            if not os.path.isdir(directory):
                if not create_dir:
                    result["reason"] = "no BPG settings directory"
                    return result
                os.makedirs(directory, exist_ok=True)
                log.info(
                    "bpg: %s did not exist -- creating it so the proxy generator "
                    "has a watch list on its first run (COMP-MEDIA-6)", directory,
                )
            content = "[General]\n"
        match = _WATCH_LINE_RE.search(content)
        current = match.group("value") if match else ""
        existing = parse_watch_folders(current)
        stale = [entry for entry in existing if _mojibake_of(entry, dirs)]
        if stale:
            # Our own pre-CR-69 entries: BPG shows them garbled and they
            # watch nothing. The ONE case this function rewrites existing
            # text -- and only with the entries the parser understood.
            existing = [entry for entry in existing if entry not in stale]
            current = ", ".join(_escape_watch_folder(entry) for entry in existing)
            log.info(
                "bpg: dropping %d garbled watch folder entr%s an earlier "
                "companion wrote with the wrong escaping (CR-69)",
                len(stale), "y" if len(stale) == 1 else "ies",
            )
        missing = [entry for entry in dirs if not _is_covered(entry, existing)]
        if not missing and not stale:
            result["ok"] = True
            return result
        room = max(0, MAX_WATCH_FOLDERS - len(existing))
        allowed = min(MAX_ADDED_PER_LAUNCH, room)
        if allowed <= 0:
            # Not silent: an editor whose list is full has BRAW that will never
            # be proxied, and "BPG ran and nothing happened" is the bug this
            # whole change exists to stop reporting as success.
            log.warning(
                "bpg: %s already lists %d watch folders -- not adding %d more",
                target, len(existing), len(missing),
            )
            result["reason"] = "watch list is full"
            return result
        if len(missing) > allowed:
            log.warning(
                "bpg: %d folder(s) need watching, adding %d this time",
                len(missing), allowed,
            )
            missing = missing[:allowed]
        addition = ", ".join(_escape_watch_folder(entry) for entry in missing)
        kept = "" if current.strip() in ("", INVALID_MARKER) else current.strip()
        value = (kept + ", " + addition) if (kept and addition) else (kept or addition)
        if match:
            start, end = match.span()
            updated = content[:start] + match.group("key") + value + content[end:]
        else:
            header = _GENERAL_RE.search(content)
            line = WATCH_KEY + "=" + value + "\n"
            if header:
                cut = header.end() + 1
                updated = content[:cut] + line + content[cut:]
            else:
                updated = "[General]\n" + line + content
        backup = target + BACKUP_SUFFIX
        if os.path.exists(target) and not os.path.exists(backup):
            try:
                with open(backup, "w", encoding="utf-8", newline="") as handle:
                    handle.write(content)
            except Exception:
                log.debug("bpg: could not back up %s", target, exc_info=True)
        with open(target, "w", encoding="utf-8", newline="") as handle:
            handle.write(updated)
    except Exception:
        log.exception("bpg: could not set the watch folders in %s", target)
        result["reason"] = "settings file could not be written"
        return result
    result["ok"] = True
    result["added"] = missing
    log.info(
        "bpg: added %d watch folder(s) to %s so the generator can see the "
        "clips ffmpeg cannot decode: %s",
        len(missing), target, "; ".join(missing),
    )
    return result


# -- the Start button (fact 4) ------------------------------------------------

def press_start(wait_seconds: int = START_WAIT_SECONDS,
                run_fn: Optional[Callable[..., Any]] = None) -> str:
    """Press Start on a BPG that is sitting Idle. Returns what happened.

    Windows-only and best-effort by design: every outcome except "pressed"
    leaves the world exactly as it was, which is the world this feature
    already lived in.
    """
    if platform.system() != "Windows":
        return "not-windows"
    script = _START_SCRIPT.replace("__WAIT__", str(int(max(0, wait_seconds))))
    runner = run_fn if run_fn is not None else subprocess.run
    try:
        out = runner(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
            capture_output=True, text=True, timeout=int(wait_seconds) + 60,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            env=resolve_bridge.sanitized_child_env(),   # COMP-MEDIA-3
        )
    except Exception:
        log.debug("bpg: the start press failed to run", exc_info=True)
        return "failed"
    if getattr(out, "returncode", 1) != 0:
        log.debug("bpg: the start press exited %s: %s",
                  getattr(out, "returncode", "?"), (getattr(out, "stderr", "") or "").strip())
        return "failed"
    answer = ((getattr(out, "stdout", "") or "").strip().splitlines() or [""])[-1].strip()
    return answer or "failed"


class BpgLauncher:
    """Starts BPG when, and only when, the ffmpeg queue has nothing left.

    Every collaborator is injectable for the same reason proxy_gen's are: the
    real ones start a video application.
    """

    def __init__(
        self,
        cfg: dict[str, Any],
        *,
        generation_enabled: bool,
        clock: Callable[[], float],
        spawn: Optional[Callable[[list[str]], Any]] = None,
        running_fn: Optional[Callable[[], bool]] = None,
        command: Optional[list[str]] = None,
        ensure_fn: Optional[Callable[..., dict[str, Any]]] = None,
        press_start_fn: Optional[Callable[[], str]] = None,
        run_async: Optional[Callable[[Callable[[], None]], None]] = None,
    ) -> None:
        self.command = command if command is not None else find_bpg_command(
            str(cfg.get("bpg_path", "") or "").strip()
        )
        # Tri-state, exactly like proxy_gen_enabled: an explicit value wins,
        # and the derivation is "wherever this machine already generates
        # proxies AND has something to launch". A machine with no Resolve
        # installed derives False rather than logging a failure every tick.
        value = cfg.get("bpg_enabled")
        if isinstance(value, bool):
            self.enabled = value
        else:
            if value is not None:
                log.error("config: bpg_enabled=%r is not true/false -- deriving it", value)
            self.enabled = bool(generation_enabled and self.command)
        # Two opt-outs rather than one, because they are two different
        # intrusions: writing a file the editor owns, and clicking a button in
        # an application they are looking at. Both default ON -- a generator
        # that watches nothing and never starts is the state this feature was
        # in for its whole life before 2026-08-13.
        self.manage_watch_folders = _flag(cfg, "bpg_manage_watch_folders", True)
        self.autostart = _flag(cfg, "bpg_autostart", True)
        self.settings_path = settings_path(
            str(cfg.get("bpg_settings_path", "") or "").strip()
        )
        self._clock = clock
        self._spawn = spawn if spawn is not None else _spawn_detached
        self._running_fn = running_fn if running_fn is not None else is_bpg_running
        self._ensure_fn = ensure_fn if ensure_fn is not None else ensure_watch_folders
        self._press_start_fn = press_start_fn if press_start_fn is not None else press_start
        self._run_async = run_async if run_async is not None else _run_detached_thread
        self._last_launch_at: Optional[float] = None
        self._last_start_press_at: Optional[float] = None
        self._child: Any = None
        # RES-16 (2026-09-04). The press runs on another thread, and this is
        # read by a status caller on a third, so it is lock-guarded even
        # though it is one string.
        self._status_lock = threading.Lock()
        self._needs_editor: Optional[str] = None
        self._launched_for = 0

    # The one thing in this whole module a human has to do, addressed to the
    # human (RES-16, 2026-09-04). Until now it was a WARNING in companion.log
    # telling an editor -- who reads no logs -- to click a button, while the
    # fleet went without BRAW proxies. The log line stays; this is the same
    # sentence where a tray or a settings window can show it.
    NEEDS_START_PRESS = (
        "CCSync opened the Blackmagic Proxy Generator to make proxies, but "
        "could not press Start. Press Start in its window."
    )

    def status(self) -> dict[str, Any]:
        """What this launcher knows, for a status reader. No I/O, no probes.

        `needs_editor` is a sentence for the editor or None: None means there
        is nothing for them to do, which is the normal state. It is cleared
        the moment a Start press succeeds, so a window somebody started by
        hand stops nagging on its own.
        """
        with self._status_lock:
            needs_editor = self._needs_editor
            launched_for = self._launched_for
        return {
            "enabled": bool(self.enabled),
            "installed": bool(self.command),
            "autostart": bool(self.autostart),
            "running": self._child_alive(),
            "clips": launched_for,
            "needs_editor": needs_editor,
        }

    def _set_needs_editor(self, sentence: Optional[str]) -> None:
        with self._status_lock:
            self._needs_editor = sentence

    def _child_alive(self) -> bool:
        return self._child is not None and self._child.poll() is None

    def _ensure_watch_folders(self, watch_dirs: Sequence[str]) -> bool:
        """True if BPG will see the pending clips when it comes up.

        `create_dir=bool(self.command)` is the real "is there a proxy
        generator here" test, and it is already answered: maybe_launch returns
        "no proxy generator installed" before this is ever reached
        (COMP-MEDIA-6, 2026-08-14).
        """
        if not self.manage_watch_folders:
            return True
        try:
            outcome = self._ensure_fn(
                watch_dirs, path=self.settings_path, create_dir=bool(self.command),
            )
        except Exception:
            log.exception("bpg: the watch-folder update raised")
            return False
        return bool(outcome.get("ok"))

    def _press_start(self, why: str) -> None:
        """Press Start off the tick thread. The window can be three minutes
        away on a cold Resolve, and the caller is proxy_gen's tick."""
        if not self.autostart:
            return
        now = self._clock()
        last = self._last_start_press_at
        if last is not None and (now - last) < START_POKE_COOLDOWN_SECONDS:
            return
        self._last_start_press_at = now

        def _press() -> None:
            answer = self._press_start_fn()
            if answer == "pressed":
                self._set_needs_editor(None)
                log.info("bpg: pressed Start (%s) -- the queue is running", why)
            elif answer in ("already-running", "not-windows"):
                self._set_needs_editor(None)
                log.debug("bpg: no start press needed (%s)", answer)
            else:
                self._set_needs_editor(self.NEEDS_START_PRESS)
                # Worth a WARNING: BPG is up, something needs encoding, and
                # nothing is happening -- which is indistinguishable from the
                # bug this replaced unless we say so.
                log.warning(
                    "bpg: could not press Start (%s) -- the proxy generator is "
                    "open but idle, press Start in its window", answer,
                )

        try:
            self._run_async(_press)
        except Exception:
            log.exception("bpg: could not run the start press")

    def maybe_launch(self, *, queue_empty: bool, needs_resolve: int,
                     user_away: Union[bool, Callable[[], bool]],
                     watch_dirs: Sequence[str] = ()) -> Optional[str]:
        """Start BPG if this is the moment. Returns a reason when it did not.

        Order is not only what gets logged any more: every condition below is
        required, and the two EXPENSIVE ones (the caller's idle probe, which
        forks ioreg on macOS, and our own PowerShell process probe) are asked
        last, after the cheap ones have already ruled the tick out (MED-8/MED-9,
        2026-08-11). `user_away` accepts a callable for exactly that reason.

        `watch_dirs` are the directories holding the clips that need BPG --
        proxy_scan collects them, because a count alone cannot tell a watcher
        where to look, and that is precisely how the base rig ended up
        launching a generator with an empty folder list (fact 3).
        """
        if not self.enabled:
            return "disabled"
        if not self.command:
            return "no proxy generator installed"
        if needs_resolve <= 0:
            return "nothing needs BPG"
        if not queue_empty:
            # The whole point of the sequencing: two encoders on one GPU.
            return "ffmpeg still has clips queued"
        if not (user_away() if callable(user_away) else user_away):
            return "user is at the keyboard"
        if self._child_alive():
            # Free: a poll() on a handle we hold. Kept ahead of the cooldown so
            # a running BPG of ours is still reported as one.
            self._press_start("it was already up")
            return "already running"
        now = self._clock()
        # The COOLDOWN before the process probe, not after: inside it the
        # probe's answer cannot change the outcome, and the probe is a
        # PowerShell spawn (MED-9).
        if (self._last_launch_at is not None
                and (now - self._last_launch_at) < RELAUNCH_COOLDOWN_SECONDS):
            return "launched too recently"
        if self._running_fn():
            # An idle BPG somebody else opened is the same dead end as one we
            # opened: clips waiting, generator up, nothing encoding.
            self._press_start("it was already up")
            return "already running"
        if not self._ensure_watch_folders(watch_dirs):
            # Launching now would repeat the 2026-08-13 failure exactly: a
            # generator watching nothing, three times a day, for months. No
            # cooldown is set -- this costs a file read, not a process.
            return "watch folders could not be set"
        try:
            self._child = self._spawn(self.command)
        except Exception:
            # Non-fatal like every other thing in this feature: the clips stay
            # in the report as needing BPG, which is what they were before.
            log.exception("bpg: could not start %s", " ".join(self.command))
            self._last_launch_at = now      # don't retry in a tight loop
            return "launch failed"
        self._last_launch_at = now
        with self._status_lock:
            self._launched_for = int(needs_resolve)
        # A BPG we just started must not be masked by a process list read
        # before it existed -- the cache is a cost saver, not a state.
        _reset_probe_cache()
        log.info(
            "bpg: started the Blackmagic Proxy Generator for %d clip(s) ffmpeg "
            "cannot decode -- watching %d folder(s), and never stopped by us",
            needs_resolve, len(watch_dirs or ()),
        )
        # Its window is Idle until something presses Start (fact 4), and that
        # window is seconds to minutes away -- off-thread, and only once the
        # spawn actually worked.
        self._press_start("it was just launched")
        return None


def _flag(cfg: dict[str, Any], key: str, default: bool) -> bool:
    """A boolean config value, with a bad one logged rather than obeyed.

    Same shape as the bpg_enabled tri-state above, minus the derivation: these
    two have a real default, so an unparseable value falls back to it.
    """
    value = cfg.get(key, None)
    if isinstance(value, bool):
        return value
    if value is not None:
        log.error("config: %s=%r is not true/false -- using %s", key, value, default)
    return default


def _run_detached_thread(target: Callable[[], None]) -> None:
    """Run something that waits, off the caller's thread.

    daemon=True: the start press can sit for three minutes waiting for a
    window, and a companion the editor quits must not stay alive for it.
    """
    threading.Thread(target=target, name="bpg-start", daemon=True).start()


def _spawn_detached(command: list[str]) -> Any:
    """Start BPG so it outlives the companion.

    DETACHED_PROCESS: the companion is a tray app an editor quits, and a proxy
    run halfway through a 40-minute BRAW clip must not die with it.

    sanitized_child_env is not optional here, and this child is the worst one
    in the package to get it wrong on (COMP-MEDIA-3, 2026-08-14): in a frozen
    build the bridge pins PYTHONHOME/PYTHON3HOME process-wide at our _MEIPASS
    (resolve_bridge:48-53), the bootloader deletes that directory when the
    tray exits -- and the child here is Resolve.exe, whose fusionscript
    locates and LoadLibrary()s its Python by exactly those two variables. This
    spawn was the one in the whole package that inherited them.
    """
    creationflags = 0
    if sys.platform == "win32":
        creationflags = (getattr(subprocess, "DETACHED_PROCESS", 0)
                         | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
    return subprocess.Popen(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=creationflags,
        close_fds=True,
        cwd=os.path.dirname(command[0]) or None,
        env=resolve_bridge.sanitized_child_env(),
    )
