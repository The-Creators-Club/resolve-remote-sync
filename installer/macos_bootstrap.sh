#!/usr/bin/env bash
#
# Creators Club Sync -- macOS editor bootstrap.
#
# Idempotent setup for a remote Resolve editor's Mac:
#   - Tailscale   (brew cask, else prints download URL)
#   - rclone      (brew, else direct tarball to ~/.local/ccsync/bin)
#   - Syncthing   (brew, else direct zip to the same bin dir) + a
#                 LaunchAgent that is written AND loaded, so the daemon is
#                 actually running (lane C is dead without it)
#   - the local sync root (--local-root, default ~/Creators_Club). On an
#     external SSD (/Volumes/<Name>/...) the volume is verified to be a REAL
#     mount -- never a leftover ghost directory -- and its UUID recorded in
#     ~/.ccsync/volume.json
#   - rclone remote config stanza template in ~/.config/rclone/rclone.conf
#   - the companion binary itself (--companion-file, else downloaded from the
#     dashboard with DASHBOARD_TOKEN and checksum-verified) plus its
#     LaunchAgent autostart entry
#   - a seeded companion config at ~/.ccsync/config.toml
#   - Resolve's Mapped Mount preference (P:\ -> the local root), edited
#     directly in Resolve's own preference files while Resolve is quit
#   - prints this machine's Syncthing device ID at the end
#
# Every step checks current state before acting and prints a line saying
# what it did or what it skipped, so this script is safe to re-run.
#
# This script does NOT run `tailscale up` (joining the tailnet) or generate
# SSH keys -- those are one-time interactive/manual steps, see
# docs/EDITOR_SETUP.md.
#
# NOTHING IN THIS FILE HAS RUN ON A REAL MAC YET (pending first real-Mac
# validation, 2026-08-03). The macOS-only paths -- diskutil, launchctl,
# xattr, the Resolve preference edit -- are written from documentation and
# research, not from a live run. Treat the first install as a supervised one.
#
# Usage:
#   ./macos_bootstrap.sh --tailnet-host truenas.tailnet.ts.net --editor-name jsmith [--dry-run]
#   ./macos_bootstrap.sh --resolve-mapping-only [--local-root /Volumes/Rig/Creators_Club]
#
# CONTRACT WITH THE ONBOARDING WIZARD (onboarding/steps.py, since 1.0.17).
# The wizard branches on three machine-readable things this script emits;
# they must move together with steps.py:
#   - "[ccsync] WARNING: CAPABILITY MISSING: <msg>" lines (capability_miss
#     below) for the hard misses: no rclone, no Syncthing, no device ID.
#   - exit code 3, and ONLY from the capability summary at the very bottom:
#     "ran to the end, but this Mac is missing a capability". Every other
#     non-zero exit means the install stopped part-way (INST-5 / B7).
#   - "[ccsync] RESOLVE-MAPPING-STATUS: <status>" after the Mapped Mount
#     step, so the wizard can surface "quit Resolve and re-run" on its
#     Finish page without scraping the human-facing summary.
set -u

INSTALLER_VERSION="1.0.19"

DRY_RUN=0
TAILNET_HOST=""
EDITOR_NAME=""
LOCAL_ROOT="$HOME/Creators_Club"
# Absolute on purpose: the SFTP session lands in the editor's home directory
# on the NAS, so a relative remote root resolves under ~/ and silently misses
# the real project tree.
REMOTE_ROOT="/mnt/tank/TheCreatorsPool/Creators_Club"
COMPANION_PATH="$HOME/.local/ccsync/bin/ccsync-companion"
COMPANION_FILE=""
COMPANION_VERSION="current"
SKIP_RESOLVE_MAPPING=0
RESOLVE_MAPPING_ONLY=0

# Overridable from the environment (the admin's onboarding tooling sets both);
# defaulted here so `set -u` never trips on them.
DASHBOARD_URL="${DASHBOARD_URL:-http://100.71.216.3:8480}"
DASHBOARD_TOKEN="${DASHBOARD_TOKEN:-}"

usage() {
    echo "Usage: $0 --tailnet-host <host> --editor-name <name> [--local-root <path>]"
    echo "          [--remote-root <abs-path>] [--companion-file <path>]"
    echo "          [--companion-version <x.y.z|current>] [--companion-path <path>]"
    echo "          [--skip-resolve-mapping] [--dry-run]"
    echo "       $0 --resolve-mapping-only [--local-root <path>] [--dry-run]"
    echo ""
    echo "  --companion-file      install the companion from a local file instead of"
    echo "                        downloading it (no DASHBOARD_TOKEN needed)"
    echo "  --companion-version   published version to fetch (default: current)"
    echo "  --companion-path      where the companion binary lives"
    echo "                        (default: \$HOME/.local/ccsync/bin/ccsync-companion)"
    echo "  --skip-resolve-mapping   leave Resolve's Mapped Mount alone"
    echo "  --resolve-mapping-only   set Resolve's Mapped Mount and do nothing else"
    exit 1
}

while [ $# -gt 0 ]; do
    case "$1" in
        --tailnet-host)
            TAILNET_HOST="$2"; shift 2 ;;
        --editor-name)
            EDITOR_NAME="$2"; shift 2 ;;
        --local-root)
            LOCAL_ROOT="$2"; shift 2 ;;
        --remote-root)
            REMOTE_ROOT="$2"; shift 2 ;;
        --companion-file)
            COMPANION_FILE="$2"; shift 2 ;;
        --companion-version)
            COMPANION_VERSION="$2"; shift 2 ;;
        --companion-path)
            COMPANION_PATH="$2"; shift 2 ;;
        --skip-resolve-mapping)
            SKIP_RESOLVE_MAPPING=1; shift ;;
        --resolve-mapping-only)
            RESOLVE_MAPPING_ONLY=1; shift ;;
        --dry-run)
            DRY_RUN=1; shift ;;
        -h|--help)
            usage ;;
        *)
            echo "Unknown argument: $1"; usage ;;
    esac
done

# --resolve-mapping-only touches nothing that needs a NAS or an account, so it
# must not demand the two arguments a full install needs -- it is the command
# the error messages below tell editors to re-run after quitting Resolve.
if [ "$RESOLVE_MAPPING_ONLY" != 1 ]; then
    if [ -z "$TAILNET_HOST" ] || [ -z "$EDITOR_NAME" ]; then
        usage
    fi
fi

step() { echo "[ccsync] $1"; }
skip() { echo "[ccsync] SKIP: $1"; }
warn() { echo "[ccsync] WARNING: $1" >&2; }
dry()  { echo "[ccsync] [dry-run] $1"; }

# Hard-capability misses (rclone absent, Syncthing absent, no device ID).
# Each one means this Mac can never sync something it is supposed to sync,
# so unlike every other warning they must NOT end in exit 0 -- the wizard
# (and a human reading the tail of the output) would take that as a green
# DONE for a machine that will never sync (INST-5). Mirrors
# windows_bootstrap.ps1's Add-CapabilityMiss, marker text and all --
# onboarding/steps.py parses the "CAPABILITY MISSING:" prefix.
CAPABILITY_MISS_COUNT=0
CAPABILITY_MISSES=""
capability_miss() {
    CAPABILITY_MISS_COUNT=$((CAPABILITY_MISS_COUNT + 1))
    CAPABILITY_MISSES="${CAPABILITY_MISSES}$1
"
    echo "[ccsync] WARNING: CAPABILITY MISSING: $1" >&2
}

# Unix usernames are case-sensitive; a case mismatch produces a
# working-looking rclone.conf that fails later with a generic SSH auth error
# giving no hint that the username was the problem.
EDITOR_NAME_RAW="$EDITOR_NAME"
EDITOR_NAME="$(printf '%s' "$EDITOR_NAME" | tr '[:upper:]' '[:lower:]')"
if [ "$EDITOR_NAME" != "$EDITOR_NAME_RAW" ]; then
    warn "normalized --editor-name '$EDITOR_NAME_RAW' -> '$EDITOR_NAME'"
fi

case "$REMOTE_ROOT" in
    /*) ;;
    *) warn "--remote-root '$REMOTE_ROOT' is not absolute. The SFTP session starts in your home directory on the NAS, so a relative path resolves under ~/ and will not find the project tree. Prefix it with '/'." ;;
esac

BIN_DIR="$HOME/.local/ccsync/bin"
CC_ROOT="$LOCAL_ROOT"
LAUNCH_AGENTS_DIR="$HOME/Library/LaunchAgents"
RCLONE_CONF_DIR="$HOME/.config/rclone"
RCLONE_CONF_PATH="$RCLONE_CONF_DIR/rclone.conf"
SYNCTHING_HOME="$HOME/.local/ccsync/syncthing-config"
KEY_FILE_PATH="$HOME/.ssh/ccsync_ed25519"
REMOTE_NAME="creators_club_sftp"
CCSYNC_CONFIG_DIR="$HOME/.ccsync"
CCSYNC_CONFIG_PATH="$CCSYNC_CONFIG_DIR/config.toml"
VOLUME_JSON_PATH="$CCSYNC_CONFIG_DIR/volume.json"
COMPANION_PLIST="$LAUNCH_AGENTS_DIR/com.creatorsclub.ccsync.companion.plist"
CANONICAL_PREFIX='P:\'

if [ "$RESOLVE_MAPPING_ONLY" = 1 ]; then
    step "ccsync macOS bootstrap $INSTALLER_VERSION -- Resolve mapping only, local root '$CC_ROOT'"
else
    step "ccsync macOS bootstrap $INSTALLER_VERSION -- editor '$EDITOR_NAME', local root '$CC_ROOT', NAS '$TAILNET_HOST'"
fi

# Private, per-run staging for downloaded archives.
#
# The fixed /tmp/ccsync-*.zip and /tmp/ccsync-*-extract paths this replaces are
# world-writable and PREDICTABLE: on a shared Mac any other local account could
# pre-create /tmp/ccsync-rclone-extract containing its own `rclone` binary (or
# win the race on the zip), and this script would copy it to $BIN_DIR and make
# it the editor's rclone_path -- a binary that then runs on every sync with
# the editor's NAS credentials. `mkdir -p` on an existing attacker-owned dir
# succeeds, and `unzip -o` would not necessarily overwrite a planted file whose
# name is not in the archive. Windows already stages per-user ($env:TEMP).
# mktemp -d creates a fresh 0700 dir owned by us, and the trap removes it.
STAGE_DIR=""
if [ "$DRY_RUN" != 1 ]; then
    STAGE_DIR="$(mktemp -d "${TMPDIR:-/tmp}/ccsync-stage.XXXXXXXX")"
    # shellcheck disable=SC2064  # expand STAGE_DIR now, on purpose
    trap "rm -rf '$STAGE_DIR'" EXIT INT TERM
fi

ensure_dir() {
    local path="$1"
    if [ -d "$path" ]; then
        skip "directory already exists: $path"
    else
        if [ "$DRY_RUN" = 1 ]; then
            dry "would create directory: $path"
        else
            mkdir -p "$path"
            step "created directory: $path"
        fi
    fi
}

have_cmd() { command -v "$1" >/dev/null 2>&1; }

# ---CCSYNC-RCLONE-STANZA-BEGIN---
# rewrite_rclone_stanza <conf-path> <section-name> <stanza-text>
#
# Replace one [section] in an rclone.conf, preserving every other remote in
# it. Returns non-zero WITHOUT touching the file if anything goes wrong.
#
# MAC-9, live on the first real Mac (2026-08-04): this used to pass the
# multi-line stanza through `awk -v stanza=...`. macOS ships BWK awk, which
# REJECTS a -v value containing a newline --
#     awk: newline in string [creators_club_sftp]... at source line 1
# -- exits 2, and writes NOTHING. The old code then chmod'd and mv'd that
# empty output over rclone.conf, so an editor re-running the installer lost
# every remote in the file, credentials included. GNU awk accepts multi-line
# -v values, which is why it survived every Linux/CI run.
#
# So: awk only DELETES the old section (single-line -v, no newline anywhere),
# the shell appends the new stanza, and nothing is swapped into place until
# awk has succeeded AND every other section that was in the original is still
# present in the result. A timestamped backup is kept either way.
rewrite_rclone_stanza() {
    _rrs_conf="$1"; _rrs_name="$2"; _rrs_stanza="$3"
    [ -f "$_rrs_conf" ] || return 1

    _rrs_tmp="$(mktemp "${_rrs_conf}.ccsync.XXXXXX")" || return 1
    if ! awk -v sect="[$_rrs_name]" '
            /^\[/ { inside = ($0 == sect) }
            !inside
        ' "$_rrs_conf" > "$_rrs_tmp"; then
        rm -f "$_rrs_tmp"
        return 1
    fi
    printf '\n%s' "$_rrs_stanza" >> "$_rrs_tmp" || { rm -f "$_rrs_tmp"; return 1; }

    # The new stanza must be there...
    if ! grep -qxF "[$_rrs_name]" "$_rrs_tmp"; then
        rm -f "$_rrs_tmp"
        return 1
    fi
    # ...and so must every OTHER section the file started with. This is the
    # check that would have caught MAC-9 before the mv.
    _rrs_lost=""
    for _rrs_sect in $(grep -o '^\[[^]]*\]' "$_rrs_conf" | grep -vxF "[$_rrs_name]"); do
        grep -qxF "$_rrs_sect" "$_rrs_tmp" || _rrs_lost="$_rrs_lost $_rrs_sect"
    done
    if [ -n "$_rrs_lost" ]; then
        rm -f "$_rrs_tmp"
        return 1
    fi

    cp "$_rrs_conf" "${_rrs_conf}.ccsync-backup-$(date +%Y%m%d-%H%M%S)" 2>/dev/null || true
    # Same permissions as the file we are replacing; rclone.conf can hold
    # credentials for other remotes.
    chmod 600 "$_rrs_tmp"
    mv "$_rrs_tmp" "$_rrs_conf"
}
# ---CCSYNC-RCLONE-STANZA-END---

# Minimal JSON string escaping -- a volume name may legitimately contain a
# quote or a backslash, and an unescaped one produces a volume.json the
# companion cannot parse.
json_escape() { printf '%s' "$1" | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g'; }

sha256_of() {
    [ -f "$1" ] || return 1
    shasum -a 256 "$1" 2>/dev/null | awk '{print $1}' | tr 'A-Z' 'a-z'
}

# ----------------------------------------------------------------------
# Resolve Mapped Mount (P:\ -> the local root)
# ----------------------------------------------------------------------
# Resolve has no scripting API for this preference, so the python3 helper
# embedded at the bottom of this file edits Resolve's own preference files
# (config.dat + .config.data) while Resolve is quit. Defined up here because
# --resolve-mapping-only runs it and exits before anything else happens.
RESOLVE_MAPPING_STATUS="unset"

# The helper's source lives in ONE place: the quoted heredoc below, between
# the sentinel comment lines. Not one character of it is expanded by the
# shell. The sentinels are load-bearing -- write_mapping_helper() seds
# between them, and companion/tests/test_resolve_mapping_helper.py extracts
# and imports the same range, so the module the tests cover is byte-for-byte
# the module the installer runs. Keep them exactly as they are.
#
# It is ~700 lines of python; the install steps resume right after it.
emit_mapping_helper() {
    cat <<'CCSYNC_MAPPING_HELPER_PY'
# ---CCSYNC-MAPPING-HELPER-BEGIN---
r"""Set DaVinci Resolve's Mapped Mount (P:\ -> a local root) on macOS.

The shared project database stores every clip path in Windows form
(P:\Projects\...). A Mac only resolves those paths if Resolve has a Mapped
Mount entry pointing P:\ at the local copy of the tree. That preference has
no scripting API, so this module edits the two plain-text preference files
Resolve keeps, WHILE RESOLVE IS QUIT:

  config.dat      the engine's mirror   (Site.<n>.FS.<i>.Root / .MappedRoot)
  .config.data    the GUI's own form    (IoFsMount_<i> / IoFsMappedMount_<i>)

Both must agree. Editing config.dat alone has no lasting effect, because the
GUI form is what Resolve rewrites config.dat from on the next launch.

Config directory, first match wins:
  1. $BMD_RESOLVE_CONFIG_DIR            (explicit override; also the test hook)
  2. ~/Library/Preferences/Blackmagic Design/DaVinci Resolve
     (no "Preferences" subfolder on macOS, unlike Windows)
  3. ~/Library/Containers/com.blackmagic-design.DaVinciResolve/Data/Library/
     Preferences/Blackmagic Design/DaVinci Resolve       (Mac App Store build)
Whichever of 2/3 contains config.dat wins. A MISSING config.dat means Resolve
has never completed its first run: this module then DEFERS, and never creates
one, because first-run onboarding regenerates the whole config anyway.

Subcommands: apply, verify (read-only), remove. Every write is atomic
(tempfile + os.replace), preceded by a timestamped backup of BOTH files, and
lossless: unknown keys, blank-line structure, indentation, spacing and the
file's line-ending style all survive untouched.

Exit codes:
  0  apply:  mapping applied, or already correct (nothing written)
     verify: mapping is present and points at --local-root
     remove: entry removed, or already absent
  2  bad usage (argparse)
  3  DaVinci Resolve is running -- quit it first, nothing was touched
  4  Resolve's preference files were not found (never launched, or a
     non-standard config directory) -- nothing was created
  5  the preference files are not in the expected format (no FS.Count / no
     IoFsNum) -- nothing was touched
  6  verify only: no mapping for the mapped root at all
  7  verify only: a mapping exists but points somewhere else
  8  the preference files could not be read or written

Pure stdlib, python3.9-compatible (macOS Command Line Tools python3), and
importable on any platform: this file is embedded verbatim in
installer/macos_bootstrap.sh between the CCSYNC-MAPPING-HELPER sentinels, and
companion/tests/test_resolve_mapping_helper.py extracts and imports it from
there -- so the code the installer runs is the code the tests cover.

NOT YET VALIDATED ON A REAL MAC (2026-08-03). The file formats and key names
come from a live Resolve 21 install plus community research; the numbering
base of .config.data's IoFs* keys is read from the file rather than assumed,
and the /Volumes auto-entry is kept last. Verify against a real Mac before
trusting it.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time

EXIT_OK = 0
EXIT_RESOLVE_RUNNING = 3
EXIT_CONFIG_MISSING = 4
EXIT_FORMAT_UNRECOGNISED = 5
EXIT_MAPPING_ABSENT = 6
EXIT_MAPPING_WRONG = 7
EXIT_IO_ERROR = 8

CONFIG_DAT_NAME = "config.dat"
CONFIG_DATA_NAME = ".config.data"
DEFAULT_MAPPED_ROOT = "P:" + "\\"

# Resolve appends its own filesystem entry for /Volumes (macOS) or the
# ResolveVirtual pseudo-mount (Windows) and expects it LAST. Ours goes in
# front of it so the renumbering leaves it last.
TRAILING_ROOTS = ("/Volumes", "ResolveVirtual")


class HelperError(Exception):
    """An error with a specific process exit code."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message


def warn(message):
    sys.stderr.write("[ccsync] WARNING: %s\n" % message)


def say(message):
    sys.stdout.write("[ccsync] %s\n" % message)


# --------------------------------------------------------------- discovery


def candidate_config_dirs(home=None):
    """The standard macOS Resolve preference directories, in priority order."""
    home = os.path.expanduser("~") if home is None else home
    return [
        os.path.join(home, "Library", "Preferences",
                     "Blackmagic Design", "DaVinci Resolve"),
        os.path.join(home, "Library", "Containers",
                     "com.blackmagic-design.DaVinciResolve", "Data", "Library",
                     "Preferences", "Blackmagic Design", "DaVinci Resolve"),
    ]


def find_config_dir(env=None, home=None):
    """Return the config directory to patch, or None when Resolve has none."""
    env = os.environ if env is None else env
    override = (env.get("BMD_RESOLVE_CONFIG_DIR") or "").strip()
    if override:
        # Used as-is: an override that holds no config.dat must still report
        # "Resolve never launched" rather than silently falling back to a
        # different profile than the caller asked for.
        return override
    for path in candidate_config_dirs(home):
        if os.path.isfile(os.path.join(path, CONFIG_DAT_NAME)):
            return path
    return None


def resolve_is_running():
    """True when a DaVinci Resolve process is up (pgrep, like the installer)."""
    try:
        proc = subprocess.run(
            ["pgrep", "-f", "DaVinci Resolve"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
    except (OSError, ValueError):
        # No pgrep (not macOS): we cannot tell, and claiming "running" would
        # block the only code path that does anything.
        return False
    return proc.returncode == 0


# -------------------------------------------------------------- path compare


def norm_local(path):
    path = (path or "").strip()
    if len(path) > 1:
        path = path.rstrip("/")
    return path


def same_local(a, b):
    return norm_local(a) == norm_local(b)


def norm_mapped(path):
    return (path or "").strip().rstrip("\\").lower()


def same_mapped(a, b):
    a, b = norm_mapped(a), norm_mapped(b)
    return bool(a) and a == b


def sep_for(sep, value):
    """The " = " between key and value, fixed up for a value being written
    into a line that used to be empty: Resolve writes "Key = " with a
    trailing space, but a file (or an editor) that trimmed it would otherwise
    give us "Key =P:\\"."""
    if value != "" and not sep.endswith((" ", "\t")):
        return sep + " "
    return sep


# ---------------------------------------------------------------- text files


class PrefFile:
    """One preference file, loaded losslessly: unknown lines, blank-line
    structure, indentation, spacing and line-ending style all survive a
    round trip untouched."""

    def __init__(self, path, lines, newline, trailing_newline, mode):
        self.path = path
        self.lines = lines
        self.newline = newline
        self.trailing_newline = trailing_newline
        self.mode = mode
        self.original = list(lines)
        # Filled in by load(); -1 means "unknown" (a hand-built instance).
        self.uid = -1

    @classmethod
    def load(cls, path):
        try:
            with open(path, "rb") as handle:
                raw = handle.read()
            info = os.stat(path)
            mode = stat.S_IMODE(info.st_mode)
            uid = info.st_uid
        except OSError as exc:
            raise HelperError(EXIT_IO_ERROR, "cannot read %s: %s" % (path, exc))
        text = raw.decode("utf-8", "surrogateescape")
        crlf = text.count("\r\n")
        lf = text.count("\n") - crlf
        newline = "\r\n" if crlf and crlf >= lf else "\n"
        lines = [ln[:-1] if ln.endswith("\r") else ln for ln in text.split("\n")]
        trailing = False
        if lines and lines[-1] == "":
            lines.pop()
            trailing = True
        handle = cls(path, lines, newline, trailing, mode)
        handle.uid = uid
        return handle

    def render(self):
        text = self.newline.join(self.lines)
        if self.trailing_newline:
            text += self.newline
        return text

    def changed(self):
        return self.lines != self.original

    def backup(self, stamp):
        dest = "%s.ccsync-backup-%s" % (self.path, stamp)
        try:
            shutil.copy2(self.path, dest)
        except OSError as exc:
            raise HelperError(EXIT_IO_ERROR,
                              "cannot back up %s: %s" % (self.path, exc))
        return dest

    def ownership_warning(self):
        """A warning string if saving will change this file's owner, else None.

        On the first real Mac (2026-08-04) `.config.data` was owned by ROOT
        with mode 666, while `config.dat` beside it was owned by the user.
        Mode 666 means the atomic save below succeeds -- but mkstemp creates
        the temp as the RUNNING user and os.replace keeps the temp's owner,
        so a root-owned file silently comes back user-owned. Harmless in all
        likelihood (Resolve runs as the user), but it is a change nothing in
        the design intended and re-running the helper cannot undo it. Say so
        rather than let it be discovered later.
        """
        if self.uid < 0:
            return None
        try:
            me = os.geteuid()
        except AttributeError:      # non-posix; the helper is macOS-only
            return None
        if self.uid == me:
            return None
        return ("%s is owned by uid %d, not you (uid %d) -- its mode allows the "
                "write, but the atomic replace will leave it owned by YOU. "
                "Nothing here can restore the original owner; note it before "
                "continuing." % (self.path, self.uid, me))

    def save(self):
        """Atomic: write a sibling temp file, match the original's mode, and
        os.replace() it over the original -- an interrupted run can never
        leave Resolve with a half-written preference file.

        Preserves MODE but not OWNER -- see ownership_warning().
        """
        payload = self.render().encode("utf-8", "surrogateescape")
        directory = os.path.dirname(self.path) or "."
        fd, tmp = tempfile.mkstemp(prefix=".ccsync-", dir=directory)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(tmp, self.mode)
            os.replace(tmp, self.path)
        except OSError as exc:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise HelperError(EXIT_IO_ERROR,
                              "cannot write %s: %s" % (self.path, exc))


class Edits:
    """Line-level edit plan, applied in one pass so every untouched line keeps
    its exact original bytes and its position relative to unknown lines."""

    def __init__(self):
        self.replace = {}
        self.drop = set()
        self.insert_before = {}

    def add_before(self, index, texts):
        self.insert_before.setdefault(index, []).extend(texts)

    def add_after(self, index, texts):
        self.add_before(index + 1, texts)

    def apply(self, lines):
        out = []
        for i, line in enumerate(lines):
            out.extend(self.insert_before.get(i, ()))
            if i in self.drop:
                continue
            out.append(self.replace.get(i, line))
        out.extend(self.insert_before.get(len(lines), ()))
        return out


class Entry:
    """One filesystem entry, as a set of key=value lines in the file."""

    def __init__(self, index):
        self.index = index
        self.values = {}
        self.formats = {}
        self.key_lines = []          # (field, line_no) in file order
        self.added = []              # (field, value) fields not in the file yet

    def add_line(self, field, line_no, value, indent, sep):
        self.key_lines.append((field, line_no))
        if field not in self.values:
            self.values[field] = value
            self.formats[field] = (indent, sep)

    def get(self, field, default=""):
        return self.values.get(field, default)

    def has(self, field):
        return field in self.values or any(f == field for f, _ in self.added)

    def set(self, field, value):
        if field in self.values:
            self.values[field] = value
        else:
            self.added = [(f, v) for f, v in self.added if f != field]
            self.added.append((field, value))

    @property
    def first_line(self):
        return min(no for _, no in self.key_lines)

    @property
    def last_line(self):
        return max(no for _, no in self.key_lines)

    def default_format(self):
        if self.key_lines:
            return self.formats[self.key_lines[0][0]]
        return ("", " = ")


class MappingFile:
    """Shared plan/rebuild logic for the two preference formats."""

    ROOT_FIELD = ""
    MAPPED_FIELD = ""
    DIO_FIELDS = ()
    NAME = ""
    BLANK_SEPARATOR = False      # does the format group entries with blanks?

    def __init__(self, pref):
        self.pref = pref
        self.warnings = []
        self.entries = []
        self.count_line = -1
        self.count_indent = ""
        self.count_sep = " = "
        self.parse()

    # -- subclass hooks ---------------------------------------------------
    def parse(self):
        raise NotImplementedError

    def key_text(self, field, position, indent, sep, value):
        raise NotImplementedError

    def count_text(self, value):
        raise NotImplementedError

    def new_entry_fields(self, local_root, mapped_root):
        raise NotImplementedError

    def insert_position(self):
        """Where the new entry goes: in front of Resolve's own trailing
        filesystem entry, if this file has one.

        Lives on the BASE class so config.dat and .config.data behave the
        same way. It used to be a ConfigDat-only override, so .config.data
        appended AFTER any /Volumes entry -- contradicting both
        MACOS_FIRST_RUN.md D5 and GOTCHAS.md, which say the trailing entry is
        kept last in both, and leaving the two files with different orderings
        for the same mapping. The first real Mac (2026-08-04) happened to
        have no /Volumes line in .config.data at all, so the divergence was
        invisible there -- but the tests exercised precisely the branch that
        is wrong.
        """
        if self.entries:
            last = (self.root_of(self.entries[-1]) or "").strip()
            for reserved in TRAILING_ROOTS:
                if last == reserved or last.startswith(reserved + "/"):
                    return len(self.entries) - 1
        return len(self.entries)

    # -- reading ----------------------------------------------------------
    def root_of(self, entry):
        return entry.get(self.ROOT_FIELD)

    def mapped_of(self, entry):
        return entry.get(self.MAPPED_FIELD)

    def entry_for_mapped(self, mapped_root):
        found = [e for e in self.entries if same_mapped(self.mapped_of(e), mapped_root)]
        if len(found) > 1:
            self.warnings.append(
                "%s has %d entries mapping %s; only the first was used"
                % (self.NAME, len(found), mapped_root))
        return found[0] if found else None

    def mapping_state(self, local_root, mapped_root):
        entry = self.entry_for_mapped(mapped_root)
        if entry is None:
            return ("absent", None)
        root = self.root_of(entry)
        return ("correct" if same_local(root, local_root) else "wrong", root)

    # -- writing ----------------------------------------------------------
    def plan_apply(self, local_root, mapped_root):
        entry = self.entry_for_mapped(mapped_root)
        if entry is not None:
            if same_local(self.root_of(entry), local_root):
                return "already-correct"
            entry.set(self.ROOT_FIELD, local_root)
            self.rebuild(list(self.entries))
            return "repointed"
        for candidate in self.entries:
            if same_local(self.root_of(candidate), local_root):
                candidate.set(self.MAPPED_FIELD, mapped_root)
                if self.DIO_FIELDS and not any(candidate.has(f) for f in self.DIO_FIELDS):
                    candidate.set(self.DIO_FIELDS[0], "1")
                self.rebuild(list(self.entries))
                return "mapped-existing"
        order = list(self.entries)
        order.insert(self.insert_position(),
                     self.new_entry_fields(local_root, mapped_root))
        self.rebuild(order)
        return "added"

    def plan_remove(self, mapped_root):
        entry = self.entry_for_mapped(mapped_root)
        if entry is None:
            return "absent"
        self.rebuild([e for e in self.entries if e is not entry])
        return "removed"

    def rebuild(self, order):
        """order: existing Entry objects and/or [(field, value), ...] lists for
        brand-new entries, in their final order."""
        edits = Edits()
        lines = self.pref.lines
        kept = [item for item in order if isinstance(item, Entry)]
        indent, sep = (kept[0].default_format() if kept
                       else (self.count_indent, self.count_sep))

        for position, item in enumerate(order, start=1):
            if not isinstance(item, Entry):
                continue
            for field, line_no in item.key_lines:
                field_indent, field_sep = item.formats.get(field, (indent, sep))
                value = item.values.get(field, "")
                text = self.key_text(field, position, field_indent,
                                     sep_for(field_sep, value), value)
                if text != lines[line_no]:
                    edits.replace[line_no] = text
            for field, value in item.added:
                edits.add_after(item.last_line,
                                [self.key_text(field, position, indent,
                                               sep_for(sep, value), value)])

        # entries that are going away
        for entry in self.entries:
            if entry in kept:
                continue
            block = sorted(no for _, no in entry.key_lines)
            edits.drop.update(block)
            after, before = block[-1] + 1, block[0] - 1
            if after < len(lines) and lines[after].strip() == "":
                edits.drop.add(after)
            elif before >= 0 and lines[before].strip() == "":
                edits.drop.add(before)

        # the brand-new entry, if any
        for position, item in enumerate(order, start=1):
            if isinstance(item, Entry):
                continue
            block = [self.key_text(field, position, indent,
                                   sep_for(sep, value), value)
                     for field, value in item]
            gap = [""] if self.BLANK_SEPARATOR else []
            following = [e for e in order[position:] if isinstance(e, Entry)]
            if following:
                edits.add_before(following[0].first_line, block + gap)
            elif kept:
                edits.add_after(kept[-1].last_line, gap + block)
            else:
                edits.add_after(self.count_line, gap + block)

        count_text = self.count_text(str(len(order)))
        if count_text != lines[self.count_line]:
            edits.replace[self.count_line] = count_text

        self.pref.lines = edits.apply(lines)


RE_FS_COUNT = re.compile(r"^(\s*)Site\.(\d+)\.FS\.Count(\s*=\s*)(.*)$")
RE_FS_FIELD = re.compile(r"^(\s*)Site\.(\d+)\.FS\.(\d+)\.([A-Za-z][A-Za-z0-9]*)(\s*=\s*)(.*)$")


class ConfigDat(MappingFile):
    """config.dat -- Site.<n>.FS.<i>.<field> = <value>."""

    ROOT_FIELD = "Root"
    MAPPED_FIELD = "MappedRoot"
    DIO_FIELDS = ("MacDIO", "DIO")
    NAME = CONFIG_DAT_NAME
    BLANK_SEPARATOR = True

    def parse(self):
        lines = self.pref.lines
        counts = []
        for i, line in enumerate(lines):
            match = RE_FS_COUNT.match(line)
            if match:
                counts.append((i, int(match.group(2)), match.group(1),
                               match.group(3), match.group(4).strip()))
        if not counts:
            raise HelperError(
                EXIT_FORMAT_UNRECOGNISED,
                "%s has no Site.<n>.FS.Count line" % self.pref.path)
        self.count_line, self.site, self.count_indent, self.count_sep, raw = counts[0]
        try:
            declared = int(raw)
        except ValueError:
            raise HelperError(
                EXIT_FORMAT_UNRECOGNISED,
                "%s has an unreadable Site.%d.FS.Count value %r"
                % (self.pref.path, self.site, raw))
        if len(counts) > 1:
            self.warnings.append(
                "%s declares filesystems for %d Sites (%s); only Site.%d was patched"
                % (self.pref.path, len(counts),
                   ", ".join(str(c[1]) for c in counts), self.site))

        found = {}
        for i, line in enumerate(lines):
            match = RE_FS_FIELD.match(line)
            if not match or int(match.group(2)) != self.site:
                continue
            index = int(match.group(3))
            entry = found.get(index)
            if entry is None:
                entry = found[index] = Entry(index)
            entry.add_line(match.group(4), i, match.group(6),
                           match.group(1), match.group(5))
        self.entries = [found[k] for k in sorted(found)]
        # Resolve's own numbering base, taken from the file rather than
        # assumed -- every sample seen so far is 1-based, but if a real
        # config.dat ever numbers from FS.0, renumbering it from 1 would
        # silently rewrite Resolve's own entries. 1-based when the file has
        # nothing to learn from (matches every observed sample).
        self.base = min(found) if found else 1
        if self.base not in (0, 1):
            self.warnings.append(
                "%s numbers its filesystems from %d; keeping that base"
                % (self.pref.path, self.base))
        if declared != len(self.entries):
            self.warnings.append(
                "%s says Site.%d.FS.Count = %d but %d entries are present; "
                "the count was corrected"
                % (self.pref.path, self.site, declared, len(self.entries)))

    def key_text(self, field, position, indent, sep, value):
        return "%sSite.%d.FS.%d.%s%s%s" % (
            indent, self.site, self.base + position - 1, field, sep, value)

    def count_text(self, value):
        return "%sSite.%d.FS.Count%s%s" % (self.count_indent, self.site,
                                           self.count_sep, value)

    def new_entry_fields(self, local_root, mapped_root):
        # MacDIO, not DIO: the key is platform-specific and Resolve ignores
        # the wrong one.
        return [("Type", "IOFileSys"),
                ("Root", local_root),
                ("MappedRoot", mapped_root),
                ("MacDIO", "1"),
                ("BrightClip", "0")]


RE_IOFS_NUM = re.compile(r"^(\s*)IoFsNum(\s*=\s*)(.*)$")
RE_IOFS_FIELD = re.compile(r"^(\s*)IoFs(MappedMount|Mount|DirectIO|[A-Za-z]+)_(\d+)(\s*=\s*)(.*)$")


class ConfigData(MappingFile):
    """.config.data -- IoFsNum / IoFs<Field>_<i> = <value>."""

    ROOT_FIELD = "Mount"
    MAPPED_FIELD = "MappedMount"
    DIO_FIELDS = ("DirectIO",)
    NAME = CONFIG_DATA_NAME

    def parse(self):
        lines = self.pref.lines
        nums = []
        for i, line in enumerate(lines):
            match = RE_IOFS_NUM.match(line)
            if match:
                nums.append((i, match.group(1), match.group(2), match.group(3).strip()))
        if not nums:
            raise HelperError(EXIT_FORMAT_UNRECOGNISED,
                              "%s has no IoFsNum line" % self.pref.path)
        self.count_line, self.count_indent, self.count_sep, raw = nums[0]
        try:
            declared = int(raw)
        except ValueError:
            raise HelperError(
                EXIT_FORMAT_UNRECOGNISED,
                "%s has an unreadable IoFsNum value %r" % (self.pref.path, raw))

        found = {}
        for i, line in enumerate(lines):
            match = RE_IOFS_FIELD.match(line)
            if not match:
                continue
            index = int(match.group(3))
            entry = found.get(index)
            if entry is None:
                entry = found[index] = Entry(index)
            entry.add_line(match.group(2), i, match.group(5),
                           match.group(1), match.group(4))
        self.entries = [found[k] for k in sorted(found)]
        # Resolve's own numbering base, taken from the file rather than
        # assumed: 0-based when there is nothing to learn from.
        self.base = min(found) if found else 0
        if self.base not in (0, 1):
            self.warnings.append(
                "%s numbers its mounts from %d; keeping that base"
                % (self.pref.path, self.base))
        if declared != len(self.entries):
            self.warnings.append(
                "%s says IoFsNum = %d but %d mounts are present; the count "
                "was corrected" % (self.pref.path, declared, len(self.entries)))

    def key_text(self, field, position, indent, sep, value):
        return "%sIoFs%s_%d%s%s" % (indent, field, self.base + position - 1, sep, value)

    def count_text(self, value):
        return "%sIoFsNum%s%s" % (self.count_indent, self.count_sep, value)

    def new_entry_fields(self, local_root, mapped_root):
        return [("Mount", local_root),
                ("MappedMount", mapped_root),
                ("DirectIO", "1")]


# ------------------------------------------------------------------ commands


def load_pair(config_dir):
    """Load both preference files, or raise with the right exit code."""
    paths = [os.path.join(config_dir, CONFIG_DAT_NAME),
             os.path.join(config_dir, CONFIG_DATA_NAME)]
    missing = [p for p in paths if not os.path.isfile(p)]
    if missing:
        raise HelperError(
            EXIT_CONFIG_MISSING,
            "%s not found -- DaVinci Resolve has not completed a first run "
            "with this preference directory (%s). Launch Resolve once, quit "
            "it, then re-run." % (", ".join(os.path.basename(p) for p in missing),
                                  config_dir))
    return ConfigDat(PrefFile.load(paths[0])), ConfigData(PrefFile.load(paths[1]))


def resolve_config_dir(args):
    config_dir = args.config_dir or find_config_dir()
    if not config_dir or not os.path.isdir(config_dir):
        raise HelperError(
            EXIT_CONFIG_MISSING,
            "no DaVinci Resolve preference directory found (looked in %s). "
            "Launch Resolve once, quit it, then re-run."
            % " and ".join(candidate_config_dirs()))
    return config_dir


def flush_warnings(files):
    for handle in files:
        for message in handle.warnings:
            warn(message)


def cmd_apply(args, running_probe):
    if running_probe():
        raise HelperError(
            EXIT_RESOLVE_RUNNING,
            "DaVinci Resolve is running. It rewrites its preferences on quit, "
            "so an edit made now would be thrown away. Quit Resolve and "
            "re-run.")
    config_dir = resolve_config_dir(args)
    dat, data = load_pair(config_dir)
    actions = [dat.plan_apply(args.local_root, args.mapped_root),
               data.plan_apply(args.local_root, args.mapped_root)]
    flush_warnings((dat, data))
    changed = [f for f in (dat, data) if f.pref.changed()]
    if not changed:
        say("Resolve already maps %s to %s (%s) -- nothing written"
            % (args.mapped_root, args.local_root, config_dir))
        return EXIT_OK
    # Before any write: a file we do not own comes back owned by us, and no
    # re-run can put that back. Warn, do not refuse -- mode 666 makes the
    # write legitimate and blocking here would strand the install.
    for handle in changed:
        message = handle.pref.ownership_warning()
        if message:
            warn(message)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    for handle in (dat, data):
        say("backed up %s" % handle.pref.backup(stamp))
    for handle in changed:
        handle.pref.save()
        say("updated %s (%s)" % (handle.pref.path,
                                 actions[0] if handle is dat else actions[1]))
    say("Resolve now maps %s to %s" % (args.mapped_root, args.local_root))
    return EXIT_OK


def cmd_verify(args, running_probe):
    config_dir = resolve_config_dir(args)
    dat, data = load_pair(config_dir)
    states = [dat.mapping_state(args.local_root, args.mapped_root),
              data.mapping_state(args.local_root, args.mapped_root)]
    names = [dat.pref.path, data.pref.path]
    if all(state == "correct" for state, _ in states):
        say("Resolve maps %s to %s" % (args.mapped_root, args.local_root))
        return EXIT_OK
    if all(state == "absent" for state, _ in states):
        say("no %s mapping in %s" % (args.mapped_root, config_dir))
        return EXIT_MAPPING_ABSENT
    for (state, root), name in zip(states, names):
        if state == "wrong":
            say("%s maps %s to %s, not %s" % (name, args.mapped_root, root,
                                              args.local_root))
        elif state == "absent":
            say("%s has no %s mapping" % (name, args.mapped_root))
    return EXIT_MAPPING_WRONG


def cmd_remove(args, running_probe):
    if running_probe():
        raise HelperError(
            EXIT_RESOLVE_RUNNING,
            "DaVinci Resolve is running -- quit it and re-run.")
    config_dir = resolve_config_dir(args)
    dat, data = load_pair(config_dir)
    dat.plan_remove(args.mapped_root)
    data.plan_remove(args.mapped_root)
    flush_warnings((dat, data))
    changed = [f for f in (dat, data) if f.pref.changed()]
    if not changed:
        say("no %s mapping to remove in %s" % (args.mapped_root, config_dir))
        return EXIT_OK
    stamp = time.strftime("%Y%m%d-%H%M%S")
    for handle in (dat, data):
        say("backed up %s" % handle.pref.backup(stamp))
    for handle in changed:
        handle.pref.save()
        say("removed the %s mapping from %s" % (args.mapped_root, handle.pref.path))
    return EXIT_OK


def build_parser():
    parser = argparse.ArgumentParser(
        prog="ccsync-resolve-mapping",
        description="Set/inspect DaVinci Resolve's Mapped Mount preference.")
    parser.add_argument("command", choices=("apply", "verify", "remove"))
    parser.add_argument("--local-root", default="",
                        help="local path the mapped root stands for")
    parser.add_argument("--mapped-root", default=DEFAULT_MAPPED_ROOT,
                        help="Windows-form prefix stored in the database")
    parser.add_argument("--config-dir", default="",
                        help="Resolve preference directory (default: "
                             "$BMD_RESOLVE_CONFIG_DIR, else the standard ones)")
    return parser


def main(argv=None, running_probe=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    running_probe = resolve_is_running if running_probe is None else running_probe
    if args.command in ("apply", "verify") and not args.local_root:
        parser.error("--local-root is required for %s" % args.command)
    # A trailing slash the caller typed must not end up in the file: Resolve
    # compares these strings, and "/Volumes/X/CC/" != "/Volumes/X/CC".
    args.local_root = norm_local(args.local_root)
    handler = {"apply": cmd_apply, "verify": cmd_verify, "remove": cmd_remove}[args.command]
    try:
        return handler(args, running_probe)
    except HelperError as exc:
        warn(exc.message)
        return exc.code


if __name__ == "__main__":
    sys.exit(main())
# ---CCSYNC-MAPPING-HELPER-END---
CCSYNC_MAPPING_HELPER_PY
}

# Extract the helper to $1, preferring sed on this script (so a hand-edited
# copy of the file is what runs) and falling back to the heredoc above, which
# is what happens when this script was piped into bash and $0 is not a file.
write_mapping_helper() {
    local dest="$1"
    if [ -r "$0" ]; then
        sed -n '/^# ---CCSYNC-MAPPING-HELPER-BEGIN---$/,/^# ---CCSYNC-MAPPING-HELPER-END---$/p' "$0" > "$dest" 2>/dev/null
        if [ -s "$dest" ]; then
            return 0
        fi
    fi
    emit_mapping_helper > "$dest"
}

resolve_mapping_manual_instructions() {
    echo "      Set it by hand instead (one-time):"
    echo "        DaVinci Resolve > Preferences (Cmd+,) > Media Storage,"
    echo "        add a Mapped Mount: local path $CC_ROOT, mapped path $CANONICAL_PREFIX"
    echo "        (see docs/EDITOR_SETUP.md step 6)"
}

run_resolve_mapping() {
    if [ "$SKIP_RESOLVE_MAPPING" = 1 ]; then
        RESOLVE_MAPPING_STATUS="skipped"
        skip "Resolve Mapped Mount (--skip-resolve-mapping)"
        return 0
    fi
    step "configuring Resolve's Mapped Mount ($CANONICAL_PREFIX -> $CC_ROOT)..."
    if [ ! -d "$CC_ROOT" ]; then
        warn "the local root $CC_ROOT does not exist (yet) -- the mapping will still be written, but Resolve cannot resolve $CANONICAL_PREFIX paths until it does."
    fi
    if ! have_cmd python3; then
        RESOLVE_MAPPING_STATUS="no-python"
        warn "python3 was not found, so Resolve's Mapped Mount was NOT set."
        warn "Install the Command Line Tools (xcode-select --install) and re-run: $0 --resolve-mapping-only"
        resolve_mapping_manual_instructions >&2
        return 0
    fi
    if [ "$DRY_RUN" = 1 ]; then
        RESOLVE_MAPPING_STATUS="dry-run"
        dry "would run the embedded helper: python3 <helper> apply --local-root \"$CC_ROOT\" --mapped-root '$CANONICAL_PREFIX' (edits Resolve's config.dat and .config.data, backing both up first)"
        return 0
    fi

    local helper rc
    helper="$STAGE_DIR/ccsync_resolve_mapping.py"
    write_mapping_helper "$helper"
    if [ ! -s "$helper" ]; then
        RESOLVE_MAPPING_STATUS="error"
        warn "could not extract the Resolve mapping helper from $0 -- Mapped Mount NOT set."
        resolve_mapping_manual_instructions >&2
        return 0
    fi

    python3 "$helper" apply --local-root "$CC_ROOT" --mapped-root "$CANONICAL_PREFIX"
    rc=$?
    case "$rc" in
        0)
            RESOLVE_MAPPING_STATUS="ok"
            step "Mapped Mount configured: $CANONICAL_PREFIX -> $CC_ROOT"
            ;;
        3)
            RESOLVE_MAPPING_STATUS="running"
            warn "Resolve is running -- quit it and re-run: $0 --resolve-mapping-only"
            warn "(Resolve rewrites its preferences when it quits, so an edit made now would be thrown away. Nothing was changed.)"
            ;;
        4)
            RESOLVE_MAPPING_STATUS="never-launched"
            warn "Resolve has never been launched on this Mac -- launch it once, quit it, then re-run: $0 --resolve-mapping-only"
            warn "(Resolve writes its preference files on first run; this script will not invent them.)"
            ;;
        5)
            RESOLVE_MAPPING_STATUS="format"
            warn "Resolve's preferences are not in the format this installer knows -- nothing was changed."
            warn "Set the Mapped Mount manually per docs/EDITOR_SETUP.md step 6:"
            resolve_mapping_manual_instructions >&2
            ;;
        *)
            RESOLVE_MAPPING_STATUS="error"
            warn "the Resolve mapping helper failed (exit $rc) -- Mapped Mount NOT set."
            resolve_mapping_manual_instructions >&2
            ;;
    esac
    return 0
}

if [ "$RESOLVE_MAPPING_ONLY" = 1 ]; then
    run_resolve_mapping
    echo "[ccsync] RESOLVE-MAPPING-STATUS: $RESOLVE_MAPPING_STATUS"
    echo ""
    if [ "$RESOLVE_MAPPING_STATUS" = "ok" ] || [ "$RESOLVE_MAPPING_STATUS" = "dry-run" ]; then
        step "done -- nothing else was touched (--resolve-mapping-only)."
        exit 0
    fi
    warn "the Mapped Mount was NOT set (see above). Nothing else was touched (--resolve-mapping-only)."
    exit 1
fi

ensure_dir "$BIN_DIR"

# ----------------------------------------------------------------------
# 1. Tailscale
# ----------------------------------------------------------------------
step "checking Tailscale..."
if have_cmd tailscale || [ -d "/Applications/Tailscale.app" ]; then
    skip "Tailscale already installed"
else
    if have_cmd brew; then
        if [ "$DRY_RUN" = 1 ]; then
            dry "would run: brew install --cask tailscale"
        else
            step "installing Tailscale via brew..."
            if brew install --cask tailscale; then
                step "Tailscale installed"
            else
                warn "brew install of tailscale failed"
            fi
        fi
    else
        warn "Homebrew not found. Download and install Tailscale manually from https://tailscale.com/download/mac then re-run this script."
        exit 1
    fi
fi

# ----------------------------------------------------------------------
# 2. rclone
# ----------------------------------------------------------------------
step "checking rclone..."
RCLONE_BIN=""
if have_cmd rclone; then
    RCLONE_BIN="$(command -v rclone)"
elif [ -x "$BIN_DIR/rclone" ]; then
    RCLONE_BIN="$BIN_DIR/rclone"
fi

if [ -n "$RCLONE_BIN" ]; then
    skip "rclone already installed: $RCLONE_BIN"
else
    installed=0
    if have_cmd brew; then
        if [ "$DRY_RUN" = 1 ]; then
            dry "would run: brew install rclone"
            installed=1
        else
            step "installing rclone via brew..."
            if brew install rclone; then
                installed=1
            else
                warn "brew install of rclone failed, falling back to direct download"
            fi
        fi
    fi
    if [ "$installed" = 0 ]; then
        ARCH="$(uname -m)"
        if [ "$ARCH" = "arm64" ]; then
            ZIP_URL="https://downloads.rclone.org/rclone-current-osx-arm64.zip"
        else
            ZIP_URL="https://downloads.rclone.org/rclone-current-osx-amd64.zip"
        fi
        ZIP_PATH="$STAGE_DIR/rclone.zip"
        EXTRACT_DIR="$STAGE_DIR/rclone-extract"
        if [ "$DRY_RUN" = 1 ]; then
            dry "would download $ZIP_URL, extract, and copy rclone to $BIN_DIR"
        else
            step "downloading rclone from $ZIP_URL ..."
            curl -fsSL "$ZIP_URL" -o "$ZIP_PATH"
            rm -rf "$EXTRACT_DIR"
            mkdir -p "$EXTRACT_DIR"
            unzip -q -o "$ZIP_PATH" -d "$EXTRACT_DIR"
            FOUND="$(find "$EXTRACT_DIR" -name rclone -type f | head -n 1)"
            if [ -z "$FOUND" ]; then
                warn "could not find rclone binary inside the downloaded zip -- install rclone manually"
            else
                cp "$FOUND" "$BIN_DIR/rclone"
                chmod +x "$BIN_DIR/rclone"
                step "installed rclone to $BIN_DIR/rclone"
            fi
        fi
    fi
fi

# Authoritative re-probe after every install route. Neither the brew branch
# nor the direct-download branch above set RCLONE_BIN, so without this it
# stays empty on a FRESH install and config.toml gets the unresolvable
# rclone_path = "rclone" that INST-7 is about.
if [ -z "$RCLONE_BIN" ]; then
    if have_cmd rclone; then
        RCLONE_BIN="$(command -v rclone)"
    elif [ -x "$BIN_DIR/rclone" ]; then
        RCLONE_BIN="$BIN_DIR/rclone"
    fi
    if [ -n "$RCLONE_BIN" ]; then
        step "rclone resolved to: $RCLONE_BIN"
    elif [ "$DRY_RUN" != 1 ]; then
        capability_miss "rclone is NOT installed. Lanes A and B -- every video upload and every proxy download -- cannot run on this Mac. Install rclone (brew install rclone, or https://rclone.org/downloads/) and re-run this script."
    fi
fi

# ----------------------------------------------------------------------
# 3. Syncthing (+ LaunchAgent autostart)
# ----------------------------------------------------------------------
step "checking Syncthing..."
SYNCTHING_BIN=""
if have_cmd syncthing; then
    SYNCTHING_BIN="$(command -v syncthing)"
elif [ -x "$BIN_DIR/syncthing" ]; then
    SYNCTHING_BIN="$BIN_DIR/syncthing"
fi

if [ -n "$SYNCTHING_BIN" ]; then
    skip "Syncthing already installed: $SYNCTHING_BIN"
else
    installed=0
    if have_cmd brew; then
        if [ "$DRY_RUN" = 1 ]; then
            dry "would run: brew install syncthing"
            installed=1
        else
            step "installing Syncthing via brew..."
            if brew install syncthing; then
                installed=1
                SYNCTHING_BIN="$(command -v syncthing)"
            else
                warn "brew install of syncthing failed, falling back to direct download"
            fi
        fi
    fi
    if [ "$installed" = 0 ]; then
        ARCH="$(uname -m)"
        if [ "$ARCH" = "arm64" ]; then
            ASSET_ARCH="arm64"
        else
            ASSET_ARCH="amd64"
        fi

        # GitHub's /releases/latest/download/<name> alias only resolves when
        # that EXACT filename exists in the release. Syncthing's assets are
        # version-named, so the unversioned alias 404s. Note macOS assets are
        # .zip (the Linux/BSD ones are .tar.gz) -- unzip, don't tar.
        resolve_syncthing_url() {
            local url tag
            url="$(curl -fsSL -H 'User-Agent: ccsync-bootstrap' \
                    https://api.github.com/repos/syncthing/syncthing/releases/latest 2>/dev/null \
                  | grep -oE '"browser_download_url": *"[^"]+"' \
                  | sed -E 's/.*"browser_download_url": *"([^"]+)".*/\1/' \
                  | grep -E "syncthing-macos-${ASSET_ARCH}-v[^/]+\.zip$" \
                  | head -n 1)"
            if [ -n "$url" ]; then
                printf '%s' "$url"
                return 0
            fi
            # Backstop: the unauthenticated API is rate-limited to 60/hour per
            # IP, so sniff the version tag out of the release redirect instead.
            tag="$(curl -fsSL -o /dev/null -w '%{url_effective}' \
                    https://github.com/syncthing/syncthing/releases/latest 2>/dev/null \
                  | sed -nE 's#.*/tag/(v[0-9][^/]*)$#\1#p')"
            if [ -n "$tag" ]; then
                printf 'https://github.com/syncthing/syncthing/releases/download/%s/syncthing-macos-%s-%s.zip' \
                    "$tag" "$ASSET_ARCH" "$tag"
                return 0
            fi
            return 1
        }

        ZIP_PATH="$STAGE_DIR/syncthing.zip"
        EXTRACT_DIR="$STAGE_DIR/syncthing-extract"
        if [ "$DRY_RUN" = 1 ]; then
            dry "would resolve the latest syncthing-macos-${ASSET_ARCH}-<version>.zip via the GitHub API, download, unzip, and copy syncthing to $BIN_DIR"
        else
            ZIP_URL="$(resolve_syncthing_url || true)"
            if [ -z "$ZIP_URL" ]; then
                warn "could not determine a Syncthing download URL -- install Syncthing manually from https://syncthing.net/downloads/ and re-run this script"
            else
                step "downloading Syncthing from $ZIP_URL ..."
                curl -fsSL "$ZIP_URL" -o "$ZIP_PATH"
                rm -rf "$EXTRACT_DIR"
                mkdir -p "$EXTRACT_DIR"
                unzip -q -o "$ZIP_PATH" -d "$EXTRACT_DIR"
                FOUND="$(find "$EXTRACT_DIR" -name syncthing -type f | head -n 1)"
                if [ -z "$FOUND" ]; then
                    warn "could not find syncthing binary inside the downloaded zip -- install Syncthing manually"
                else
                    cp "$FOUND" "$BIN_DIR/syncthing"
                    chmod +x "$BIN_DIR/syncthing"
                    SYNCTHING_BIN="$BIN_DIR/syncthing"
                    step "installed Syncthing to $BIN_DIR/syncthing"
                fi
            fi
        fi
    fi
fi
if [ "$DRY_RUN" = 1 ] && [ -z "$SYNCTHING_BIN" ]; then
    SYNCTHING_BIN="$BIN_DIR/syncthing"
fi
if [ "$DRY_RUN" != 1 ] && [ -z "$SYNCTHING_BIN" ]; then
    capability_miss "Syncthing is NOT installed. Lane C -- audio, After Effects projects, graphics, subtitles, .drp project files and docs -- will never sync on this Mac. Install Syncthing (brew install syncthing, or https://syncthing.net/downloads/) and re-run this script."
fi

# Generate the config/keys before the daemon is launched, so the device ID
# is stable and the LaunchAgent doesn't race a first-run key generation.
if [ "$DRY_RUN" = 1 ]; then
    dry "would run: $SYNCTHING_BIN generate --home=$SYNCTHING_HOME (if not already generated)"
elif [ -z "$SYNCTHING_BIN" ]; then
    # With set -u but no set -e, `"" generate ...` is a silently-ignored
    # "command not found" -- and everything downstream then assumed a config
    # existed. Say so instead.
    warn "Syncthing is not installed, so no Syncthing config was generated."
else
    if [ ! -d "$SYNCTHING_HOME" ]; then
        step "generating Syncthing config at $SYNCTHING_HOME ..."
        "$SYNCTHING_BIN" generate --home="$SYNCTHING_HOME" >/dev/null 2>&1
    else
        skip "Syncthing config already generated at $SYNCTHING_HOME"
    fi
fi

SYNCTHING_PLIST="$LAUNCH_AGENTS_DIR/com.creatorsclub.ccsync.syncthing.plist"
ensure_dir "$LAUNCH_AGENTS_DIR"

# Returns the first <string> inside a plist's ProgramArguments array, i.e.
# the program the agent actually runs. Empty when it can't be determined.
plist_program() {
    [ -f "$1" ] || return 0
    sed -n '/<key>ProgramArguments<\/key>/,/<\/array>/p' "$1" \
      | grep -o '<string>[^<]*</string>' \
      | head -n 1 \
      | sed -E 's#</?string>##g'
}

# Reload a LaunchAgent we just rewrote. bootout+bootstrap is the modern form;
# unload+load is the fallback on older macOS.
reload_agent() {
    local plist="$1"
    launchctl bootout "gui/$(id -u)" "$plist" >/dev/null 2>&1 || true
    launchctl unload "$plist" >/dev/null 2>&1 || true
    if launchctl bootstrap "gui/$(id -u)" "$plist" 2>/dev/null; then
        return 0
    fi
    launchctl load "$plist" 2>/dev/null
}

# INST-8: a failed brew/curl leaves SYNCTHING_BIN empty (set -u, no set -e),
# and the old code happily wrote a plist whose ProgramArguments[0] was
# <string></string>. Because the guard was "does the file exist", EVERY later
# run -- including one after the editor installed Syncthing by hand -- printed
# "already present" and never repaired it. So: never write a plist with an
# empty program, and make the guard compare the embedded path against the
# binary we found, rewriting and reloading on a mismatch.
SYNCTHING_PLIST_PROGRAM="$(plist_program "$SYNCTHING_PLIST")"
if [ -z "$SYNCTHING_BIN" ]; then
    warn "Syncthing was not installed, so no LaunchAgent was written (an agent with no program to run can never be repaired by a later run of this script)."
    warn "Install Syncthing (brew install syncthing, or https://syncthing.net/downloads/) and re-run this script."
    if [ -f "$SYNCTHING_PLIST" ] && [ -z "$SYNCTHING_PLIST_PROGRAM" ]; then
        warn "Removing the broken agent left by an earlier run: $SYNCTHING_PLIST"
        if [ "$DRY_RUN" != 1 ]; then
            launchctl bootout "gui/$(id -u)" "$SYNCTHING_PLIST" >/dev/null 2>&1 || true
            rm -f "$SYNCTHING_PLIST"
        fi
    fi
elif [ -f "$SYNCTHING_PLIST" ] && [ "$SYNCTHING_PLIST_PROGRAM" = "$SYNCTHING_BIN" ]; then
    skip "Syncthing LaunchAgent already present and correct: $SYNCTHING_PLIST"
else
    if [ -f "$SYNCTHING_PLIST" ]; then
        step "Syncthing LaunchAgent points at '$SYNCTHING_PLIST_PROGRAM' but Syncthing is at '$SYNCTHING_BIN' -- rewriting it"
    fi
    if [ "$DRY_RUN" = 1 ]; then
        dry "would write LaunchAgent plist: $SYNCTHING_PLIST (runs $SYNCTHING_BIN serve --home=$SYNCTHING_HOME)"
    else
        cat > "$SYNCTHING_PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.creatorsclub.ccsync.syncthing</string>
    <key>ProgramArguments</key>
    <array>
        <string>$SYNCTHING_BIN</string>
        <string>serve</string>
        <string>--home=$SYNCTHING_HOME</string>
        <string>--no-browser</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
</dict>
</plist>
PLIST
        step "wrote Syncthing LaunchAgent: $SYNCTHING_PLIST"
        # A rewritten plist means launchd is still running the OLD program
        # until the agent is reloaded -- which is the whole point of repairing
        # it (INST-8).
        if reload_agent "$SYNCTHING_PLIST"; then
            step "reloaded the Syncthing LaunchAgent"
        else
            warn "could not reload $SYNCTHING_PLIST -- it will take effect at your next logon, or reload it now with:"
            warn "    launchctl bootout gui/\$(id -u) \"$SYNCTHING_PLIST\"; launchctl bootstrap gui/\$(id -u) \"$SYNCTHING_PLIST\""
        fi
    fi
fi

# Writing the plist is not enough -- until it is loaded there is no running
# daemon, no REST API on 127.0.0.1:8384, and lane C never syncs at all.
if [ "$DRY_RUN" = 1 ]; then
    dry "would load the Syncthing LaunchAgent and confirm the daemon is running"
elif [ -z "$SYNCTHING_BIN" ]; then
    warn "no Syncthing binary -- skipping the daemon start. Lane C (audio, After Effects projects, graphics, subtitles, .drp project files, docs) will not sync on this Mac until Syncthing is installed and this script re-run."
else
    if pgrep -qx syncthing 2>/dev/null || pgrep -f "syncthing.*serve" >/dev/null 2>&1; then
        skip "Syncthing daemon already running"
    else
        # bootstrap/gui is the modern form; fall back to `load` on older macOS.
        if launchctl bootstrap "gui/$(id -u)" "$SYNCTHING_PLIST" 2>/dev/null; then
            step "loaded Syncthing LaunchAgent (launchctl bootstrap)"
        elif launchctl load "$SYNCTHING_PLIST" 2>/dev/null; then
            step "loaded Syncthing LaunchAgent (launchctl load)"
        else
            warn "could not load $SYNCTHING_PLIST automatically -- start the daemon by hand with:"
            warn "    launchctl bootstrap gui/\$(id -u) \"$SYNCTHING_PLIST\""
        fi

        # Give it a moment, then confirm rather than assume.
        sleep 2
        if pgrep -qx syncthing 2>/dev/null || pgrep -f "syncthing.*serve" >/dev/null 2>&1; then
            step "Syncthing daemon is running"
        else
            warn "Syncthing daemon does not appear to be running yet -- check 'launchctl list | grep ccsync' and $SYNCTHING_HOME"
        fi
    fi
fi

# Seed the NAS as a known device via the RUNNING instance's REST API (an XML
# edit behind a live daemon is silently overwritten). Without this entry a
# fresh config drops every NAS connection as "unknown device" one second
# after hello, in a permanent reconnect loop (alex_laptop, 2026-07-26).
# autoAcceptFolders stays false on purpose: the companion's sequencer accepts
# folder offers at the CORRECT local path, while Syncthing's own auto-accept
# mangles this deployment's slash-labelled folders into flat directories.
NAS_SYNCTHING_ID="${CCSYNC_NAS_SYNCTHING_ID:-CPGHYGU-KI5UFOR-GPOGIEP-5EW6BIP-ZNJNVY3-Q5GI5PN-TGI346D-MTKBSQR}"
if [ "$DRY_RUN" = 1 ]; then
    dry "would seed the NAS device $NAS_SYNCTHING_ID (addresses tcp://$TAILNET_HOST:22000, dynamic) into the running Syncthing via REST"
elif [ -n "$NAS_SYNCTHING_ID" ] && [ -f "$SYNCTHING_HOME/config.xml" ]; then
    ST_API_KEY="$(sed -n 's#.*<apikey>\([^<]*\)</apikey>.*#\1#p' "$SYNCTHING_HOME/config.xml" | head -n 1)"
    if [ -z "$ST_API_KEY" ]; then
        warn "no API key in $SYNCTHING_HOME/config.xml -- cannot seed the NAS device"
    else
        st_alive=0
        for _i in 1 2 3 4 5 6 7 8 9 10; do
            st_ping_code="$(curl -s -o /dev/null -w '%{http_code}' -H "X-API-Key: $ST_API_KEY" \
                http://127.0.0.1:8384/rest/system/ping 2>/dev/null || true)"
            if [ "$st_ping_code" = "200" ]; then st_alive=1; break; fi
            if [ "$st_ping_code" = "401" ] || [ "$st_ping_code" = "403" ]; then
                warn "the Syncthing at 127.0.0.1:8384 rejected this config's API key -- a Syncthing from a different home owns the port. NOT seeding the NAS device."
                break
            fi
            sleep 1
        done
        if [ "$st_alive" = 1 ]; then
            if curl -s -H "X-API-Key: $ST_API_KEY" http://127.0.0.1:8384/rest/config/devices \
                | grep -q "$NAS_SYNCTHING_ID"; then
                skip "NAS device already in the Syncthing config"
            else
                st_seed_code="$(curl -s -o /dev/null -w '%{http_code}' -X POST \
                    -H "X-API-Key: $ST_API_KEY" -H "Content-Type: application/json" \
                    -d "{\"deviceID\":\"$NAS_SYNCTHING_ID\",\"name\":\"truenas\",\"addresses\":[\"tcp://$TAILNET_HOST:22000\",\"dynamic\"],\"compression\":\"metadata\",\"introducer\":false,\"paused\":false,\"autoAcceptFolders\":false}" \
                    http://127.0.0.1:8384/rest/config/devices 2>/dev/null || true)"
                if [ "$st_seed_code" = "200" ]; then
                    step "seeded the NAS device into Syncthing -- pairing needs no GUI clicks on either side"
                else
                    warn "could not seed the NAS Syncthing device (HTTP $st_seed_code)"
                fi
            fi
        elif [ "$st_ping_code" != "401" ] && [ "$st_ping_code" != "403" ]; then
            warn "Syncthing REST at 127.0.0.1:8384 did not come up -- NOT seeding the NAS device (re-run this script once it is running)"
        fi
    fi
fi

# ----------------------------------------------------------------------
# 4. Local sync root (usually an external SSD)
# ----------------------------------------------------------------------
# The Mac editors keep the tree on a plug-in SSD, which macOS mounts at
# /Volumes/<Name>. Two failure modes have to be refused rather than adapted
# to, because adapting silently syncs terabytes to the wrong place:
#
#   * a GHOST DIRECTORY. An unclean eject can leave a plain, empty
#     /Volumes/<Name> directory behind on the boot disk. It looks exactly
#     like the mounted volume to `[ -d ]`, so every check based on "does the
#     path exist" passes -- and the whole sync then lands on the internal
#     drive, filling it.
#   * a NUMBERED REMOUNT. With that ghost directory in place, the real SSD
#     mounts at "/Volumes/<Name> 1" instead. Following it would bake a name
#     that changes on the next replug into config.toml and into Resolve's
#     Mapped Mount.
#
# The fix for both is the same and belongs to the human: eject, remove the
# leftover directory, replug. So: verify, explain, and abort.
mounted_paths() {
    # `mount` prints "<device> on <path> (<opts>)" -- volume names contain
    # spaces, so cut on " on " / " (" instead of whitespace fields.
    mount 2>/dev/null | sed -n 's/^.* on \(.*\) (.*)$/\1/p'
}

is_mount_point() {
    mounted_paths | grep -qxF "$1"
}

# Prints "/Volumes/<Name> 1"-style siblings that ARE mounted, if any.
numbered_variant_of() {
    local base="$1" mp found=""
    while IFS= read -r mp; do
        case "$mp" in
            "$base "[0-9]|"$base "[0-9][0-9]) found="$mp"; break ;;
        esac
    done <<VOLUMES
$(mounted_paths)
VOLUMES
    printf '%s' "$found"
}

ghost_directory_abort() {
    local mount_point="$1" numbered="$2"
    echo "" >&2
    warn "**********************************************************************"
    warn "$mount_point IS NOT A MOUNTED VOLUME."
    warn ""
    if [ -n "$numbered" ]; then
        warn "Your drive is actually mounted at:"
        warn "    $numbered"
        warn ""
        warn "That happens when a leftover directory already occupies"
        warn "$mount_point, so macOS mounts the real drive under a numbered"
        warn "name. The numbered name changes between replugs, so it must NOT"
        warn "be used as the sync root."
    else
        warn "There is a directory at that path, but nothing is mounted on it --"
        warn "the classic leftover from an unclean eject. Syncing into it would"
        warn "fill your Mac's internal disk instead of the SSD."
    fi
    warn ""
    warn "Fix it, then re-run this script:"
    warn "  1. eject the drive (Finder, or: diskutil eject \"$mount_point\")"
    warn "  2. remove the leftover directory:"
    warn "       sudo rmdir \"$mount_point\""
    warn "     (rmdir, not rm -rf: it refuses if the directory is NOT empty,"
    warn "      which would mean real files live there and you need help.)"
    warn "  3. unplug and replug the drive, confirm it appears as"
    warn "     $mount_point, and run this script again."
    warn "**********************************************************************"
    echo "" >&2
    exit 1
}

CC_VOLUME_MOUNT=""
CC_VOLUME_UUID=""
CC_VOLUME_FSTYPE=""
case "$CC_ROOT" in
    /Volumes/*)
        CC_VOLUME_REST="${CC_ROOT#/Volumes/}"
        CC_VOLUME_MOUNT="/Volumes/${CC_VOLUME_REST%%/*}"
        step "local root is on the external volume $CC_VOLUME_MOUNT -- verifying it is really mounted..."
        if [ "$DRY_RUN" = 1 ]; then
            dry "would verify $CC_VOLUME_MOUNT is a real mount (diskutil info -plist + mount), read its VolumeUUID, and write $VOLUME_JSON_PATH (mode 600)"
        else
            CC_NUMBERED="$(numbered_variant_of "$CC_VOLUME_MOUNT")"
            if [ ! -d "$CC_VOLUME_MOUNT" ]; then
                if [ -n "$CC_NUMBERED" ]; then
                    ghost_directory_abort "$CC_VOLUME_MOUNT" "$CC_NUMBERED"
                fi
                warn "$CC_VOLUME_MOUNT does not exist -- plug the drive in (and unlock it if it is encrypted), then re-run this script."
                exit 1
            fi
            if ! is_mount_point "$CC_VOLUME_MOUNT"; then
                ghost_directory_abort "$CC_VOLUME_MOUNT" "$CC_NUMBERED"
            fi
            if [ -n "$CC_NUMBERED" ]; then
                warn "another volume is mounted at '$CC_NUMBERED' as well. $CC_VOLUME_MOUNT is a real mount so this run continues, but two drives with the same name are how the wrong one gets synced -- rename one of them."
            fi
            CC_VOL_PLIST="$STAGE_DIR/volinfo.plist"
            if ! diskutil info -plist "$CC_VOLUME_MOUNT" > "$CC_VOL_PLIST" 2>/dev/null; then
                warn "diskutil does not recognise $CC_VOLUME_MOUNT as a volume, even though something is mounted there. Refusing to guess -- check 'diskutil list' and 'mount', then re-run."
                exit 1
            fi
            # plutil is the supported reader; the sed fallback covers the
            # older plutil that has no -extract.
            CC_VOLUME_UUID="$(plutil -extract VolumeUUID raw -o - "$CC_VOL_PLIST" 2>/dev/null | head -n 1 | tr -d '\r')"
            if [ -z "$CC_VOLUME_UUID" ]; then
                CC_VOLUME_UUID="$(sed -n '/<key>VolumeUUID<\/key>/{n;s#.*<string>\(.*\)</string>.*#\1#p;}' "$CC_VOL_PLIST" | head -n 1)"
            fi
            CC_VOLUME_FSTYPE="$(plutil -extract FilesystemType raw -o - "$CC_VOL_PLIST" 2>/dev/null | head -n 1 | tr -d '\r')"
            if [ -z "$CC_VOLUME_FSTYPE" ]; then
                CC_VOLUME_FSTYPE="$(sed -n '/<key>FilesystemType<\/key>/{n;s#.*<string>\(.*\)</string>.*#\1#p;}' "$CC_VOL_PLIST" | head -n 1)"
            fi
            if [ -z "$CC_VOLUME_UUID" ]; then
                warn "could not read a VolumeUUID for $CC_VOLUME_MOUNT. The volume record will be written without one, and the companion's root guard will have only the mount point to go on."
            else
                step "volume $CC_VOLUME_MOUNT is mounted (UUID $CC_VOLUME_UUID, filesystem ${CC_VOLUME_FSTYPE:-unknown})"
            fi
            case "$CC_VOLUME_FSTYPE" in
                apfs|APFS) ;;
                "") warn "could not determine the filesystem of $CC_VOLUME_MOUNT." ;;
                *) warn "$CC_VOLUME_MOUNT is formatted $CC_VOLUME_FSTYPE, not APFS. exFAT/HFS+ drives lose macOS metadata and, on exFAT, cannot store the case-sensitive names some project trees use. APFS is what this deployment is tested against." ;;
            esac

            # Contract with the companion: its root guard reads this file to
            # tell "the SSD is unplugged" (do nothing, wait) apart from "the
            # SSD is mounted but empty" (a real problem), and refreshes it
            # when the volume legitimately changes.
            ensure_dir "$CCSYNC_CONFIG_DIR"
            chmod 700 "$CCSYNC_CONFIG_DIR" 2>/dev/null || true
            cat > "$VOLUME_JSON_PATH" <<VOLJSON
{
  "volume_uuid": "$(json_escape "$CC_VOLUME_UUID")",
  "mount_point": "$(json_escape "$CC_VOLUME_MOUNT")",
  "local_root": "$(json_escape "$CC_ROOT")"
}
VOLJSON
            chmod 600 "$VOLUME_JSON_PATH" 2>/dev/null || warn "could not chmod 600 $VOLUME_JSON_PATH"
            step "recorded the sync volume in $VOLUME_JSON_PATH"
        fi
        ;;
    *)
        skip "local root $CC_ROOT is not under /Volumes -- no external-volume checks"
        ;;
esac

ensure_dir "$CC_ROOT"

# ----------------------------------------------------------------------
# 5. rclone remote config stanza
# ----------------------------------------------------------------------
ensure_dir "$RCLONE_CONF_DIR"

STANZA="[$REMOTE_NAME]
type = sftp
host = $TAILNET_HOST
user = $EDITOR_NAME
port = 22
key_file = $KEY_FILE_PATH
shell_type = unix
"

has_section=0
existing_host=""
existing_user=""
if [ -f "$RCLONE_CONF_PATH" ] && grep -qF "[$REMOTE_NAME]" "$RCLONE_CONF_PATH"; then
    has_section=1
    # Read host/user from THIS stanza only: awk from its header to the next
    # bracketed header (or EOF).
    existing_host="$(awk -v sect="[$REMOTE_NAME]" '
        $0 == sect { inside=1; next }
        /^\[/      { inside=0 }
        inside && /^[[:space:]]*host[[:space:]]*=/ {
            sub(/^[[:space:]]*host[[:space:]]*=[[:space:]]*/, ""); print; exit
        }' "$RCLONE_CONF_PATH")"
    existing_user="$(awk -v sect="[$REMOTE_NAME]" '
        $0 == sect { inside=1; next }
        /^\[/      { inside=0 }
        inside && /^[[:space:]]*user[[:space:]]*=/ {
            sub(/^[[:space:]]*user[[:space:]]*=[[:space:]]*/, ""); print; exit
        }' "$RCLONE_CONF_PATH")"
fi

if [ "$has_section" = 1 ] && [ "$existing_host" = "$TAILNET_HOST" ] && [ "$existing_user" = "$EDITOR_NAME" ]; then
    skip "rclone.conf already has a correct [$REMOTE_NAME] section: $RCLONE_CONF_PATH"
elif [ "$has_section" = 1 ]; then
    # INST-17: the single most likely reason to re-run this script is a
    # typo'd --editor-name, and skipping the whole stanza whenever the
    # section exists made that re-run a silent no-op for the one file that
    # carries the username. Rewrite this stanza in place; every other remote
    # in the file is preserved.
    warn "rclone.conf's [$REMOTE_NAME] disagrees with the values you passed:"
    warn "  host: '$existing_host' -> '$TAILNET_HOST'"
    warn "  user: '$existing_user' -> '$EDITOR_NAME'"
    if [ "$DRY_RUN" = 1 ]; then
        dry "would rewrite the [$REMOTE_NAME] stanza in $RCLONE_CONF_PATH (other remotes untouched):"
        echo "$STANZA"
    elif rewrite_rclone_stanza "$RCLONE_CONF_PATH" "$REMOTE_NAME" "$STANZA"; then
        step "rewrote the [$REMOTE_NAME] stanza in $RCLONE_CONF_PATH (host=$TAILNET_HOST, user=$EDITOR_NAME)"
    else
        warn "could not rewrite the [$REMOTE_NAME] stanza in $RCLONE_CONF_PATH -- it was LEFT UNTOUCHED, nothing was lost."
        warn "Fix it by hand: set host = $TAILNET_HOST and user = $EDITOR_NAME under [$REMOTE_NAME], then re-run this script."
    fi
else
    if [ "$DRY_RUN" = 1 ]; then
        dry "would append this stanza to $RCLONE_CONF_PATH :"
        echo "$STANZA"
    else
        printf '\n%s\n' "$STANZA" >> "$RCLONE_CONF_PATH"
        step "appended [$REMOTE_NAME] stanza to $RCLONE_CONF_PATH"
    fi
fi

if [ ! -f "$KEY_FILE_PATH" ]; then
    warn "SSH private key not found at $KEY_FILE_PATH -- generate a keypair (ssh-keygen -t ed25519 -f \"$KEY_FILE_PATH\"), send the .pub file to the admin for server/setup_editor_account.py, and this rclone remote will start working."
fi

# ----------------------------------------------------------------------
# 6. Companion binary
# ----------------------------------------------------------------------
# The companion is what actually syncs. It is a single binary at
# $COMPANION_PATH (NOT a .app bundle -- the LaunchAgent execs it directly, so
# there is no `open -a` indirection and launchd can see the real process).
COMPANION_READY=0
COMPANION_MISSING=1
COMPANION_FAIL_REASON=""

step "checking the companion at $COMPANION_PATH..."
COMPANION_INSTALLED_SHA=""
if [ -f "$COMPANION_PATH" ]; then
    COMPANION_INSTALLED_SHA="$(sha256_of "$COMPANION_PATH" || true)"
fi

COMPANION_SOURCE=""
COMPANION_SOURCE_SHA=""
if [ -n "$COMPANION_FILE" ]; then
    if [ ! -f "$COMPANION_FILE" ]; then
        COMPANION_FAIL_REASON="--companion-file '$COMPANION_FILE' does not exist"
        warn "$COMPANION_FAIL_REASON"
    elif [ "$DRY_RUN" = 1 ]; then
        dry "would install the companion from $COMPANION_FILE to $COMPANION_PATH"
        COMPANION_READY=1
    else
        COMPANION_SOURCE="$COMPANION_FILE"
        COMPANION_SOURCE_SHA="$(sha256_of "$COMPANION_FILE" || true)"
        step "companion source: $COMPANION_FILE (sha256 ${COMPANION_SOURCE_SHA:-unknown})"
    fi
elif [ -z "$DASHBOARD_TOKEN" ]; then
    COMPANION_FAIL_REASON="no --companion-file was given and DASHBOARD_TOKEN is not set, so there was nothing to install from"
    if [ -n "$COMPANION_INSTALLED_SHA" ]; then
        # Something is already installed; leave it alone and say so.
        COMPANION_FAIL_REASON=""
        skip "companion already installed at $COMPANION_PATH -- no DASHBOARD_TOKEN, so it was not checked for updates"
        COMPANION_READY=1
    fi
else
    COMPANION_URL="${DASHBOARD_URL%/}/api/v1/companion/package/macos/$COMPANION_VERSION"
    if [ "$DRY_RUN" = 1 ]; then
        dry "would download $COMPANION_URL (X-CCSync-Token), verify it against the X-CCSync-SHA256 header, and install it to $COMPANION_PATH"
        COMPANION_READY=1
    else
        COMPANION_DL="$STAGE_DIR/ccsync-companion.download"
        COMPANION_HDRS="$STAGE_DIR/ccsync-companion.headers"
        step "downloading the companion from $COMPANION_URL ..."
        if ! curl -fsSL -H "X-CCSync-Token: $DASHBOARD_TOKEN" -D "$COMPANION_HDRS" \
                -o "$COMPANION_DL" "$COMPANION_URL"; then
            COMPANION_FAIL_REASON="the download from $COMPANION_URL failed (wrong DASHBOARD_TOKEN, no tailnet route to the dashboard, or no published macOS package)"
            warn "$COMPANION_FAIL_REASON"
        else
            COMPANION_EXPECTED_SHA="$(grep -i '^X-CCSync-SHA256:' "$COMPANION_HDRS" 2>/dev/null \
                | tail -n 1 | sed -E 's/^[^:]*:[[:space:]]*//' | tr -d '\r' | tr 'A-Z' 'a-z')"
            COMPANION_SOURCE_SHA="$(sha256_of "$COMPANION_DL" || true)"
            if [ -z "$COMPANION_EXPECTED_SHA" ]; then
                # No header, no verification, no install: an unverified binary
                # that runs with the editor's NAS credentials is exactly what
                # the checksum is for.
                COMPANION_FAIL_REASON="the dashboard sent no X-CCSync-SHA256 header, so the download could not be verified and was NOT installed"
                warn "$COMPANION_FAIL_REASON"
            elif [ "$COMPANION_EXPECTED_SHA" != "$COMPANION_SOURCE_SHA" ]; then
                COMPANION_FAIL_REASON="the downloaded companion does not match its published checksum (expected $COMPANION_EXPECTED_SHA, got ${COMPANION_SOURCE_SHA:-none}) -- NOT installed"
                warn "$COMPANION_FAIL_REASON"
                warn "Tell the admin: either the published package is corrupt or something is rewriting the download."
            else
                COMPANION_SOURCE="$COMPANION_DL"
                step "downloaded companion verified against its published sha256"
            fi
        fi
    fi
fi

if [ -n "$COMPANION_SOURCE" ]; then
    if [ -n "$COMPANION_INSTALLED_SHA" ] && [ "$COMPANION_INSTALLED_SHA" = "$COMPANION_SOURCE_SHA" ]; then
        skip "companion already installed and identical (sha256 $COMPANION_INSTALLED_SHA)"
        COMPANION_READY=1
    else
        ensure_dir "$(dirname "$COMPANION_PATH")"
        # A running companion holds its own binary open; boot the agent out
        # first so the replacement is not fighting a live process. Best
        # effort -- a fresh install has no agent to boot out.
        if [ -f "$COMPANION_PLIST" ]; then
            launchctl bootout "gui/$(id -u)" "$COMPANION_PLIST" >/dev/null 2>&1 || true
        fi
        COMPANION_STAGED="${COMPANION_PATH}.ccsync-new"
        if ! cp "$COMPANION_SOURCE" "$COMPANION_STAGED"; then
            COMPANION_FAIL_REASON="could not stage the companion at $COMPANION_STAGED"
            warn "$COMPANION_FAIL_REASON"
            rm -f "$COMPANION_STAGED"
        else
            chmod +x "$COMPANION_STAGED"
            mv "$COMPANION_STAGED" "$COMPANION_PATH"
            # Downloaded files carry com.apple.quarantine, and a quarantined
            # binary launched by launchd fails with no visible dialog at all.
            xattr -d com.apple.quarantine "$COMPANION_PATH" 2>/dev/null || true
            step "installed the companion: $COMPANION_PATH (sha256 ${COMPANION_SOURCE_SHA:-unknown})"
            COMPANION_READY=1
        fi
    fi
fi

if [ "$COMPANION_READY" = 1 ]; then
    COMPANION_MISSING=0
fi

# ----------------------------------------------------------------------
# 6a. Companion LaunchAgent
# ----------------------------------------------------------------------
if [ "$COMPANION_MISSING" = 1 ]; then
    # INST-6: this used to be one skippable WARNING line in the middle of an
    # otherwise successful-looking run that ended with "Bootstrap complete"
    # and a device ID -- so a Mac editor reasonably concluded they were set
    # up. They are not: without the companion there are NO sync lanes, no
    # popup fixer, no dashboard reporting and no project selection on this
    # machine. Say that unmissably.
    echo ""
    warn "**********************************************************************"
    warn "THE SYNC APP IS NOT INSTALLED ON THIS MAC."
    warn ""
    warn "Reason: ${COMPANION_FAIL_REASON:-no companion binary at $COMPANION_PATH}"
    warn ""
    warn "That app is what actually syncs. Without it, NOTHING on this Mac will:"
    warn "  - upload your camera originals to the NAS      (lane A)"
    warn "  - download proxies from the NAS                (lane B)"
    warn "  - sync audio / AE / graphics / subtitles / .drp (lane C)"
    warn "  - report status to the dashboard, or let you pick projects"
    warn ""
    warn "Everything else this script configured (Tailscale, rclone, Syncthing,"
    warn "the rclone remote) is real and correct, but this Mac cannot sync on"
    warn "its own until the companion is installed. Re-run this script with"
    warn "DASHBOARD_TOKEN set, or with --companion-file pointing at the macOS"
    warn "build the admin sent you."
    warn "**********************************************************************"
    echo ""
    # An agent pointing at a binary that is not there just spams launchd
    # errors on every logon, and a later successful run would skip it as
    # "already present". Remove ours.
    if [ -f "$COMPANION_PLIST" ] && [ ! -f "$COMPANION_PATH" ]; then
        if [ "$DRY_RUN" = 1 ]; then
            dry "would remove the companion LaunchAgent left by an earlier run: $COMPANION_PLIST"
        else
            warn "removing the companion LaunchAgent left by an earlier run: $COMPANION_PLIST"
            launchctl bootout "gui/$(id -u)" "$COMPANION_PLIST" >/dev/null 2>&1 || true
            rm -f "$COMPANION_PLIST"
        fi
    fi
else
    COMPANION_PLIST_PROGRAM="$(plist_program "$COMPANION_PLIST")"
    COMPANION_PLIST_OK=0
    if [ -f "$COMPANION_PLIST" ] && [ "$COMPANION_PLIST_PROGRAM" = "$COMPANION_PATH" ] \
       && grep -q "AbandonProcessGroup" "$COMPANION_PLIST" 2>/dev/null \
       && ! grep -q "KeepAlive" "$COMPANION_PLIST" 2>/dev/null; then
        COMPANION_PLIST_OK=1
    fi
    if [ "$COMPANION_PLIST_OK" = 1 ]; then
        skip "companion LaunchAgent already present and correct: $COMPANION_PLIST"
    else
        if [ -f "$COMPANION_PLIST" ]; then
            step "companion LaunchAgent needs rewriting (runs '$COMPANION_PLIST_PROGRAM'; the companion is at '$COMPANION_PATH')"
        fi
        if [ "$DRY_RUN" = 1 ]; then
            dry "would write LaunchAgent plist: $COMPANION_PLIST (runs $COMPANION_PATH directly)"
        else
            ensure_dir "$LAUNCH_AGENTS_DIR"
            # NO KeepAlive, deliberately. The companion upgrades itself by
            # replacing its own binary and re-execing; with KeepAlive, launchd
            # ALSO restarts the process it just saw exit, and the machine ends
            # up running two companions that fight over the single-instance
            # lock and the sync queue.
            #
            # AbandonProcessGroup, also deliberately: without it launchd kills
            # the whole process group when the main process exits, which takes
            # the freshly re-execed upgrade child with it. (Both flagged for
            # first real-Mac validation.)
            cat > "$COMPANION_PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.creatorsclub.ccsync.companion</string>
    <key>ProgramArguments</key>
    <array>
        <string>$COMPANION_PATH</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>AbandonProcessGroup</key>
    <true/>
</dict>
</plist>
PLIST
            step "wrote companion LaunchAgent: $COMPANION_PLIST"
            # Same trap as the Syncthing agent: a written-but-unloaded plist
            # does nothing until the next logon, and a REWRITTEN one leaves
            # launchd running the old program until it is booted out first.
            if reload_agent "$COMPANION_PLIST"; then
                step "loaded companion LaunchAgent"
            else
                warn "could not load $COMPANION_PLIST automatically -- it will start at your next logon, or load it now with:"
                warn "    launchctl bootstrap gui/\$(id -u) \"$COMPANION_PLIST\""
            fi
        fi
    fi
fi

# ----------------------------------------------------------------------
# 6b. Companion config, seeded with what this script already knows
# ----------------------------------------------------------------------
# The companion's own first-run template leaves these blank, which silently
# yields a non-functional install -- notably `remote`, which must match the
# rclone remote name created above.

# rclone_path must be absolute (see the config below). Fall back to the bare
# name only when rclone genuinely isn't installed -- there is nothing better
# to write, and the companion's own error message is then accurate.
RCLONE_PATH_VALUE="$RCLONE_BIN"
if [ -z "$RCLONE_PATH_VALUE" ]; then
    RCLONE_PATH_VALUE="rclone"
    warn "rclone was not found, so config.toml gets rclone_path = \"rclone\" -- lanes A and B will not work until rclone is installed and this script re-run."
fi

if [ -f "$CCSYNC_CONFIG_PATH" ]; then
    skip "companion config already exists: $CCSYNC_CONFIG_PATH"
    if [ "$DRY_RUN" != 1 ]; then
        # Repair permissions on a config an older run wrote under the default
        # umask -- it holds the fleet dashboard_token (SEC-14).
        chmod 700 "$CCSYNC_CONFIG_DIR" 2>/dev/null || true
        chmod 600 "$CCSYNC_CONFIG_PATH" 2>/dev/null || true
    fi
    # Repair a bare or dead rclone_path when rclone's real location is known.
    # This branch is the NORMAL one in the wizard flow -- onboarding writes
    # config.toml (from the companion's defaults, rclone_path = "rclone")
    # BEFORE running this script, so the seeding below never fires there --
    # and launchd's PATH (/usr/bin:/bin:/usr/sbin:/sbin) can never resolve a
    # bare name: lanes A and B would report "rclone not found on PATH"
    # forever (INST-7). Only rewrites when the current value is relative or
    # points at nothing; an admin's working absolute path is never touched.
    if [ -n "$RCLONE_BIN" ] && [ "$DRY_RUN" != 1 ]; then
        CURRENT_RCLONE_PATH="$(sed -n 's/^[[:space:]]*rclone_path[[:space:]]*=[[:space:]]*"\(.*\)".*/\1/p' "$CCSYNC_CONFIG_PATH" | head -n 1)"
        NEEDS_RCLONE_REPAIR=0
        case "$CURRENT_RCLONE_PATH" in
            "$RCLONE_BIN") ;;                                    # already right
            /*) [ -x "$CURRENT_RCLONE_PATH" ] || NEEDS_RCLONE_REPAIR=1 ;;
            *)  NEEDS_RCLONE_REPAIR=1 ;;                         # blank or relative
        esac
        if [ "$NEEDS_RCLONE_REPAIR" = 1 ]; then
            RCONF_TMP="$(mktemp "${CCSYNC_CONFIG_PATH}.ccsync.XXXXXX")"
            if grep -q '^[[:space:]]*rclone_path[[:space:]]*=' "$CCSYNC_CONFIG_PATH"; then
                awk -v rp="$RCLONE_BIN" '
                    !done && /^[[:space:]]*rclone_path[[:space:]]*=/ { printf "rclone_path = \"%s\"\n", rp; done=1; next }
                    { print }
                ' "$CCSYNC_CONFIG_PATH" > "$RCONF_TMP"
            else
                cat "$CCSYNC_CONFIG_PATH" > "$RCONF_TMP"
                printf '\n# -- set by macos_bootstrap.sh --\nrclone_path = "%s"\n' "$RCLONE_BIN" >> "$RCONF_TMP"
            fi
            chmod 600 "$RCONF_TMP"
            mv "$RCONF_TMP" "$CCSYNC_CONFIG_PATH"
            step "repaired rclone_path in $CCSYNC_CONFIG_PATH: '${CURRENT_RCLONE_PATH:-<absent>}' -> '$RCLONE_BIN' (a bare name never resolves under launchd's PATH)"
        fi
    fi
    step "  confirm these values match, the companion will not fix them for you:"
    echo "      editor_name = \"$EDITOR_NAME\""
    echo "      local_root  = \"$CC_ROOT\""
    echo "      remote      = \"$REMOTE_NAME\""
    echo "      remote_root = \"$REMOTE_ROOT\""
    echo "      rclone_path = \"${RCLONE_BIN:-rclone}\""
elif [ "$DRY_RUN" = 1 ]; then
    dry "would write seeded companion config to $CCSYNC_CONFIG_PATH"
else
    ensure_dir "$CCSYNC_CONFIG_DIR"
    cat > "$CCSYNC_CONFIG_PATH" <<TOML
# ccsync-companion config -- seeded by macos_bootstrap.sh.
# See companion/README.md for the full reference. Restart the companion
# after editing this file.

editor_name = "$EDITOR_NAME"

# This machine's local copy of the project tree. Resolve's Mapped Mount
# preference points P:\ here -- macos_bootstrap.sh sets that up.
local_root = "$CC_ROOT"

# The shared-drive prefix used in Resolve's stored clip paths.
canonical_prefix = "P:\\\\"

# Must match the rclone remote name in ~/.config/rclone/rclone.conf.
remote = "$REMOTE_NAME"

# ABSOLUTE path on the NAS. The SFTP session starts in your home directory,
# so a relative value here would resolve under ~/ and miss the real tree.
remote_root = "$REMOTE_ROOT"

# OPTIONAL. Lanes A and B replicate the whole local_root <-> remote_root
# tree, so every Projects/<year>/<series>/<project> folder syncs whatever
# these say. They only affect two things: active_project is the destination
# the popup fixer suggests for media you add from outside the tree, and
# projects pairs positionally with syncthing_folder_ids for lane C's
# folder-ID check. Example:
#   projects = ["Projects/2026/Creator Profiles/Season 1"]
#   active_project = "Projects/2026/Creator Profiles/Season 1"
projects = []
active_project = ""

poll_interval = 3
scan_interval_up = 300
scan_interval_down = 120
watch_debounce_seconds = 10
transfers = 4

syncthing_url = "http://127.0.0.1:8384"
syncthing_api_key = ""
syncthing_folder_ids = []

# ABSOLUTE path, not the bare name "rclone". The companion is started by a
# LaunchAgent, and launchd gives it PATH=/usr/bin:/bin:/usr/sbin:/sbin --
# neither /opt/homebrew/bin nor ~/.local/ccsync/bin is on it, so
# rclone_available()'s shutil.which("rclone") fails and lanes A/B report
# "rclone not found on PATH" forever (INST-7).
rclone_path = "$RCLONE_PATH_VALUE"

log_path = "~/.ccsync/companion.log"
log_level = "INFO"

# Sync dashboard: reporting, managed one-at-a-time sync, and the tray's
# "Open dashboard" link. Tailnet address; token from the admin. Override
# at bootstrap time via DASHBOARD_URL / DASHBOARD_TOKEN env vars.
dashboard_url = "$DASHBOARD_URL"
dashboard_token = "$DASHBOARD_TOKEN"
TOML
    # SEC-14: this file carries the fleet dashboard_token, and `cat >` uses
    # the default umask (world-readable on a stock Mac). Lock down both the
    # file and the directory -- ~/.ccsync also holds identity.json.
    chmod 700 "$CCSYNC_CONFIG_DIR" 2>/dev/null || warn "could not chmod 700 $CCSYNC_CONFIG_DIR"
    chmod 600 "$CCSYNC_CONFIG_PATH" 2>/dev/null || warn "could not chmod 600 $CCSYNC_CONFIG_PATH"
    step "wrote seeded companion config: $CCSYNC_CONFIG_PATH (mode 600, dir 700 -- it holds the dashboard token)"
    step "  the whole project tree syncs as-is; set active_project in that file only if you want popup-fixed media filed into a specific project."
fi

# ----------------------------------------------------------------------
# 6c. Resolve's Mapped Mount preference
# ----------------------------------------------------------------------
run_resolve_mapping
# Machine-readable echo of RESOLVE_MAPPING_STATUS for the wizard (see the
# contract comment at the top); the human-facing wording is in the summary.
echo "[ccsync] RESOLVE-MAPPING-STATUS: $RESOLVE_MAPPING_STATUS"

# ----------------------------------------------------------------------
# 7. Print Syncthing device ID
# ----------------------------------------------------------------------
# `syncthing --device-id` was removed in Syncthing v2 (exits 80, "unknown
# flag"). `generate` prints the ID on every run and is safe to re-run against
# an existing home ("Key exists; will not overwrite"), so parse it from
# there, keeping the old flag as a fallback for v1 installs.
device_id_from_generate() {
    "$SYNCTHING_BIN" generate --home="$SYNCTHING_HOME" 2>&1 \
      | grep -oE '[A-Z0-9]{7}(-[A-Z0-9]{7}){7}' \
      | head -n 1
}

device_id_legacy() {
    "$SYNCTHING_BIN" --device-id --home="$SYNCTHING_HOME" 2>/dev/null \
      | grep -oE '[A-Z0-9]{7}(-[A-Z0-9]{7}){7}' \
      | head -n 1
}

# The Mapped Mount line of the closing summary, worded for what actually
# happened rather than for what was intended.
print_resolve_mapping_step() {
    case "$RESOLVE_MAPPING_STATUS" in
        ok)
            echo "   6. DONE FOR YOU: Resolve maps $CANONICAL_PREFIX to $CC_ROOT"
            echo "      (check in Preferences > Media Storage if you want to see it)"
            ;;
        running)
            echo "   6. NOT DONE -- Resolve was running. Quit Resolve completely,"
            echo "      then run:  $0 --resolve-mapping-only"
            ;;
        never-launched)
            echo "   6. NOT DONE -- Resolve has never been launched on this Mac."
            echo "      Launch it once, quit it, then run:"
            echo "        $0 --resolve-mapping-only"
            ;;
        format)
            echo "   6. NOT DONE -- Resolve's preferences are in a format this"
            echo "      installer does not recognise. Set the Mapped Mount by hand:"
            resolve_mapping_manual_instructions
            ;;
        skipped)
            echo "   6. SKIPPED (--skip-resolve-mapping). Resolve needs a Mapped"
            echo "      Mount before $CANONICAL_PREFIX paths resolve on this Mac:"
            resolve_mapping_manual_instructions
            ;;
        *)
            echo "   6. NOT DONE -- the Mapped Mount could not be set automatically."
            resolve_mapping_manual_instructions
            ;;
    esac
}

step "determining this machine's Syncthing device ID..."
if [ "$DRY_RUN" = 1 ]; then
    dry "would parse the device ID from: $SYNCTHING_BIN generate --home=$SYNCTHING_HOME"
    echo ""
    echo "=================================================================="
    echo " Bootstrap complete (dry run). No changes were made."
    echo "=================================================================="
else
    DEVICE_ID=""
    if [ -n "$SYNCTHING_BIN" ]; then
        DEVICE_ID="$(device_id_from_generate)"
        if [ -z "$DEVICE_ID" ]; then
            DEVICE_ID="$(device_id_legacy)"
        fi
    fi

    echo ""
    echo "=================================================================="
    echo " Bootstrap complete (installer $INSTALLER_VERSION)."
    echo ""
    if [ -z "$DEVICE_ID" ]; then
        capability_miss "the Syncthing device ID could NOT be determined. The admin cannot approve this Mac without it, so lane C (audio, AE, graphics, subtitles, .drp project files, docs) will never sync. Get it from the Syncthing web UI at http://127.0.0.1:8384 under Actions > Show ID and send it to the admin."
        echo " Get it from the Syncthing web UI (http://127.0.0.1:8384)"
        echo " under Actions > Show ID, and send that to the admin."
    else
        echo " Your Syncthing device ID is:"
        echo ""
        echo "     $DEVICE_ID"
        echo ""
        echo " Send this device ID to the admin so they can approve this machine"
        echo " on the dashboard. There is no per-project sharing step for you to"
        echo " do -- once you're approved, ticking a project on the dashboard"
        echo " is what shares it."
    fi
    echo ""
    echo " Remaining manual steps (see docs/EDITOR_SETUP.md):"
    echo "   1. tailscale up   (join the tailnet, one-time interactive login)"
    echo "   2. generate an SSH keypair for rclone if you haven't already:"
    echo "        ssh-keygen -t ed25519 -f \"$KEY_FILE_PATH\""
    echo "      and send the .pub file to the admin"
    if [ "$COMPANION_MISSING" = 1 ]; then
        echo "   3. INSTALL THE SYNC APP -- it is not on this Mac yet (see the"
        echo "      block above). Until it is, there is no menu-bar icon and"
        echo "      nothing syncs."
    else
        echo "   3. SIGN IN: right-click the CCSync menu-bar icon and choose"
        echo "      \"Sign in...\", using the SAME TrueNAS username and password"
        echo "      the admin gave you. NOTHING SYNCS UNTIL YOU DO THIS -- signing"
        echo "      in on the dashboard WEBSITE is not the same thing."
    fi
    echo "   4. connect DaVinci Resolve to the Project Server"
    echo "   5. Playback > Proxy Handling > Prefer Proxies"
    print_resolve_mapping_step
    echo "   7. do NOT mount any NAS share over SMB alongside this -- see the"
    echo "      drive-letter/mount warning in docs/EDITOR_SETUP.md"
    echo "=================================================================="

    # Last line seen, so the one thing that invalidates everything above
    # cannot scroll away (INST-6).
    if [ "$COMPANION_MISSING" = 1 ]; then
        echo ""
        warn "REMINDER: THE SYNC APP IS NOT INSTALLED ON THIS MAC."
        warn "${COMPANION_FAIL_REASON:-no companion binary at $COMPANION_PATH}"
        warn "companion NOT installed -- pass DASHBOARD_TOKEN or --companion-file"
        warn "and re-run this script. Tailscale, rclone, Syncthing and the rclone"
        warn "remote are configured, but nothing will sync by itself and step 3"
        warn "above has no menu-bar icon to right-click. Do not report yourself"
        warn "ready."
        echo ""
        exit 1
    fi

    # Capability summary -- the ONLY exit 3 in this script, and the only
    # non-zero exit that means "ran to the end". Everything above warns and
    # carries on (correct: a half-installed Mac beats an aborted one), but
    # exiting 0 with a hard miss on the books is how a machine that can never
    # sync gets reported as set up (INST-5). Mirrors windows_bootstrap.ps1's
    # section 11; onboarding/steps.py keys on this exact exit code.
    if [ "$CAPABILITY_MISS_COUNT" -gt 0 ]; then
        echo ""
        warn "=================================================================="
        warn "THIS MAC IS NOT READY TO SYNC -- $CAPABILITY_MISS_COUNT required piece(s) are missing:"
        MISS_INDEX=0
        while IFS= read -r miss; do
            [ -z "$miss" ] && continue
            MISS_INDEX=$((MISS_INDEX + 1))
            echo "[ccsync]   $MISS_INDEX. $miss" >&2
        done <<CAPS
$CAPABILITY_MISSES
CAPS
        warn "Everything else installed fine. Fix the above and re-run this script -- it is safe to re-run."
        warn "Do NOT tell the admin you are set up yet."
        warn "=================================================================="
        exit 3
    fi
fi
exit 0
